"""Local LLM client for the research layer.

Strict M2 constraints (plan sections 8 and 9):

- The endpoint must resolve to a loopback address. It is re-validated on
  construction AND on every request; there is no path to a cloud endpoint.
- No credentials: the client accepts an optional bearer token (LM Studio
  optionally sets one locally) but never logs or persists it.
- Bounded: a hard per-job call budget and per-call timeout; exhaustion and
  timeouts are classified errors, not silent retries.
- The client is the ONLY code in the repository that makes model network
  calls, and only from the research layer, which can never execute trades.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from email.message import Message
from http.client import HTTPResponse
from typing import Any, IO, cast

from ..config.models import LLMSettings
from ..exceptions import TradingAgentError
from ..security.loopback import is_loopback_url
from .sanitization import sanitize_text


class ModelClientError(TradingAgentError):
    """Base class for classified model errors (safe to persist/display)."""


class ModelUnreachableError(ModelClientError):
    """The local endpoint did not answer (not running, wrong port)."""


class ModelTimeoutError(ModelClientError):
    """The model did not respond within the configured timeout."""


class ModelHttpError(ModelClientError):
    """The endpoint answered with a non-2xx status."""

    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message)
        self.status = status


class ModelBudgetError(ModelClientError):
    """The per-job call budget was exhausted."""


class ModelMalformedError(ModelClientError):
    """The endpoint answered but the body was not a valid completion."""


@dataclass(frozen=True)
class ModelResponse:
    """One completed model call. Text passes through evaluation/sanitization
    before persistence; nothing here is written to the database directly."""

    text: str
    model: str
    latency_ms: int
    tokens_out: int
    usage: dict[str, Any] = field(default_factory=dict)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> None:
        raise urllib.error.HTTPError(req.full_url, code, "redirect denied", headers, fp)


def _open_local(request: urllib.request.Request, timeout: float) -> HTTPResponse:
    if not is_loopback_url(request.full_url):
        raise ModelClientError("non-loopback inference request denied")
    return cast(
        HTTPResponse,
        urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open(
            request,
            timeout=timeout,
        ),
    )


class LocalModelClient:
    """A budgeted, loopback-only OpenAI-compatible chat client (urllib; no SDK)."""

    def __init__(
        self,
        settings: LLMSettings,
        *,
        base_url: str | None = None,
        model: str | None = None,
        call_budget: int | None = None,
    ) -> None:
        url = (base_url or settings.base_url).rstrip("/")
        if not is_loopback_url(url):
            raise ModelClientError("refusing non-loopback inference endpoint")
        self._base_url = url
        self._model = model if model is not None else settings.model_id
        token = settings.auth_token
        self._token = token.get_secret_value() if token is not None else None
        self._timeout = settings.job_timeout_seconds
        self._budget = (
            call_budget if call_budget is not None else settings.max_calls_per_research_job
        )
        self.calls_made = 0

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def model(self) -> str | None:
        return self._model

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _post_json(self, path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        url = f"{self._base_url}{path}"
        if not is_loopback_url(url):  # defense in depth on every request
            raise ModelClientError("refusing non-loopback inference request")
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=self._headers(), method="POST")
        try:
            started = time.monotonic()
            with _open_local(request, timeout=self._timeout) as response:
                latency_ms = int((time.monotonic() - started) * 1000)
                raw = response.read(1_048_577).decode("utf-8", errors="replace")
        except TimeoutError:
            raise ModelTimeoutError(f"model did not respond within {self._timeout}s") from None
        except urllib.error.HTTPError as exc:
            raise ModelHttpError(
                f"model endpoint returned HTTP {exc.code}", status=exc.code
            ) from None
        except urllib.error.URLError:
            raise ModelUnreachableError("local model endpoint unreachable") from None
        if len(raw) > 1_048_576:
            raise ModelMalformedError("model response exceeds byte budget")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise ModelMalformedError("model endpoint returned non-JSON body") from None
        if not isinstance(parsed, dict):
            raise ModelMalformedError("model endpoint returned a non-object JSON body")
        return parsed, latency_ms

    def list_models(self) -> tuple[str, ...]:
        """GET /models. Used by the capability probe and admin pages."""
        url = f"{self._base_url}/models"
        request = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with _open_local(request, timeout=min(self._timeout, 10.0)) as response:
                data = json.loads(response.read(1_048_577).decode("utf-8", errors="replace"))
        except TimeoutError:
            raise ModelTimeoutError("model endpoint did not respond") from None
        except urllib.error.HTTPError as exc:
            raise ModelHttpError(
                f"model endpoint returned {exc.code} for /models", status=exc.code
            ) from None
        except urllib.error.URLError:
            raise ModelUnreachableError("local model endpoint unreachable") from None
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ModelMalformedError("invalid model list")
        models = tuple(
            str(entry.get("id", ""))
            for entry in data.get("data", ())
            if isinstance(entry, dict) and entry.get("id")
        )
        return models

    def is_available(self) -> bool:
        try:
            self.list_models()
        except ModelClientError:
            return False
        return True

    def complete(self, system: str, user: str, *, max_tokens: int = 512) -> ModelResponse:
        """One bounded chat completion. Increments the per-job call budget."""
        if self.calls_made >= self._budget:
            raise ModelBudgetError(f"per-job model call budget exhausted ({self._budget} calls)")
        self.calls_made += 1
        system, user = sanitize_text(system)[0], sanitize_text(user)[0]
        if self._token:
            system, user = (
                system.replace(self._token, "[REDACTED]"),
                user.replace(self._token, "[REDACTED]"),
            )
        payload: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }
        if self._model:
            payload["model"] = self._model
        data, latency_ms = self._post_json("/chat/completions", payload)
        try:
            text = data["choices"][0]["message"]["content"]
            if not isinstance(text, str):
                raise ModelMalformedError("model content must be text")
            if self._token and self._token in text:
                raise ModelMalformedError("model echoed a private credential")
        except (KeyError, IndexError, TypeError):
            raise ModelMalformedError("model response missing choices[0].message.content") from None
        raw_usage = data.get("usage")
        if not isinstance(raw_usage, dict):
            raw_usage = {}
        usage = {
            k: v
            for k, v in raw_usage.items()
            if k in {"prompt_tokens", "completion_tokens", "total_tokens"}
            and isinstance(v, int)
            and not isinstance(v, bool)
            and 0 <= v <= 10_000_000
        }
        return ModelResponse(
            text=text,
            model=self._model or "unknown",
            latency_ms=latency_ms,
            tokens_out=int(usage.get("completion_tokens") or 0),
            usage=usage,
        )
