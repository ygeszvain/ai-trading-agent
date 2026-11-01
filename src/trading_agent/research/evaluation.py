"""Output evaluation for research jobs (plan section 8: evaluation, output
validation, classification, comparison).

Every model response passes through ``evaluate_output`` before persistence:
it is classified (ok / invalid_output / model_error), sanitized, and checked
against a strict schema. Invalid or over-budget output is persisted as
classified data — never silently dropped, never executed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .sanitization import sanitize_text

VALID_VIEWS = frozenset({"bullish", "bearish", "neutral", "insufficient_data"})
MAX_RESPONSE_CHARS = 4000
MAX_LIST_ITEMS = 4
MAX_ITEM_CHARS = 120


@dataclass(frozen=True)
class EvaluatedOutput:
    """The result of evaluating one model response."""

    output_status: str  # ok | invalid_output | model_error
    response_text: str | None  # sanitized
    structured: dict | None
    error_class: str | None
    error_message: str | None


def _sanitize_json_string(value: str) -> str:
    return sanitize_text(value)[:MAX_ITEM_CHARS]


def _validate_structured(data: object) -> EvaluatedOutput:
    if not isinstance(data, dict):
        return _invalid("not a JSON object")
    view = data.get("view")
    if not isinstance(view, str) or view not in VALID_VIEWS:
        return _invalid(f"view must be one of {sorted(VALID_VIEWS)}")
    confidence = data.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= float(confidence) <= 1
    ):
        return _invalid("confidence must be a number in [0, 1]")

    def _string_list(key: str) -> tuple[str, ...] | None:
        raw = data.get(key, [])
        if not isinstance(raw, list) or len(raw) > MAX_LIST_ITEMS:
            return None
        return tuple(_sanitize_json_string(str(item)) for item in raw)

    key_factors = _string_list("key_factors")
    if key_factors is None:
        return _invalid(f"key_factors must be a list of strings (max {MAX_LIST_ITEMS})")
    risk_flags = _string_list("risk_flags")
    if risk_flags is None:
        return _invalid(f"risk_flags must be a list of strings (max {MAX_LIST_ITEMS})")
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return _invalid("summary must be a non-empty string")
    agrees = data.get("agrees_with_strategy")
    if not isinstance(agrees, bool):
        return _invalid("agrees_with_strategy must be a boolean")
    structured = {
        "view": view,
        "confidence": float(confidence),
        "key_factors": list(key_factors),
        "risk_flags": list(risk_flags),
        "summary": sanitize_text(summary)[:500],
        "agrees_with_strategy": agrees,
    }
    return EvaluatedOutput(
        output_status="ok",
        response_text=sanitize_text(json.dumps(structured, sort_keys=True)),
        structured=structured,
        error_class=None,
        error_message=None,
    )


def _invalid(reason: str) -> EvaluatedOutput:
    return EvaluatedOutput(
        output_status="invalid_output",
        response_text=None,
        structured=None,
        error_class="invalid_output",
        error_message=reason,
    )


def _model_error(error: Exception) -> EvaluatedOutput:
    return EvaluatedOutput(
        output_status="model_error",
        response_text=None,
        structured=None,
        error_class=type(error).__name__,
        error_message=str(error)[:500],
    )


def evaluate_output(text: str, *, prompt_version: str) -> EvaluatedOutput:
    """Classify and sanitize one model response for a prompt version."""
    if not text.strip():
        return _invalid("empty response")
    if len(text) > MAX_RESPONSE_CHARS:
        text = text[:MAX_RESPONSE_CHARS]
    if prompt_version == "v2":
        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = candidate.strip("`")
            if candidate.lower().startswith("json"):
                candidate = candidate[4:]
            candidate = candidate.strip()
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return _invalid("response is not valid JSON")
        return _validate_structured(parsed)
    # v1: free-form prose — sanitized and length-bounded only.
    return EvaluatedOutput(
        output_status="ok",
        response_text=sanitize_text(text),
        structured=None,
        error_class=None,
        error_message=None,
    )
