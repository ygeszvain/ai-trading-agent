"""Configuration loading: YAML file + environment overlay.

Precedence (highest wins): environment variables > YAML file > built-in
defaults. The environment variables are exactly those named in build plan
section 9. A missing configuration file or any invalid value fails with a
ConfigError listing every violation; startup must fail clearly, never
silently.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError

from ..exceptions import ConfigError
from .models import TradingConfig

DEFAULT_CONFIG_FILENAMES = ("config/simulation.yaml", "simulation.yaml")

# Plan section 9 environment variable names -> (section, key).
_ENV_OVERRIDES: dict[str, tuple[str, str]] = {
    "TRADING_MODE": ("app", "mode"),
    "LIVE_TRADING_ENABLED": ("live", "enabled"),
    "LLM_PROVIDER": ("llm", "provider"),
    "LM_STUDIO_BASE_URL": ("llm", "base_url"),
    "LM_STUDIO_MODEL_ID": ("llm", "model_id"),
    "LM_STUDIO_API_TOKEN": ("llm", "auth_token"),
    "LLM_ALLOW_CLOUD_FALLBACK": ("llm", "allow_cloud_fallback"),
    "TRADING_AGENT_WEB_HOST": ("app", "web_host"),
    "TRADING_AGENT_WEB_PORT": ("app", "web_port"),
}

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


class ConfigEnvironment:
    """A read-only view over environment variables used by the loader."""

    def __init__(self, data: Mapping[str, str] | None = None) -> None:
        self._data = dict(os.environ if data is None else data)

    def get(self, key: str) -> str | None:
        value = self._data.get(key)
        if value is not None and value.strip() == "":
            return None
        return value

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None


def _resolve_config_path(explicit: str | None, env: ConfigEnvironment) -> Path:
    if explicit is not None:
        return Path(explicit)
    from_env = env.get("TRADING_AGENT_CONFIG")
    if from_env is not None:
        return Path(from_env)
    for candidate in DEFAULT_CONFIG_FILENAMES:
        path = Path(candidate)
        if path.exists():
            return path
    return Path(DEFAULT_CONFIG_FILENAMES[0])


def _parse_env_bool(raw: str, name: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ConfigError([f"{name}: {raw!r} is not a boolean (expected true/false)"])


def _apply_env_overrides(data: dict[str, Any], env: ConfigEnvironment) -> None:
    for env_name, (section, key) in _ENV_OVERRIDES.items():
        raw = env.get(env_name)
        if raw is None:
            continue
        section_data = data.setdefault(section, {})
        if not isinstance(section_data, dict):
            raise ConfigError([f"{env_name}: section {section!r} must be a mapping"])
        if key == "enabled" or key == "allow_cloud_fallback":
            section_data[key] = _parse_env_bool(raw, env_name)
        elif key == "web_port":
            try:
                section_data[key] = int(raw)
            except ValueError as exc:
                raise ConfigError([f"{env_name}: {raw!r} is not an integer port"]) from exc
        elif key == "auth_token":
            section_data[key] = raw
        else:
            section_data[key] = raw


def _load_yaml(path: Path, violations: list[str]) -> dict[str, Any] | None:
    if not path.exists():
        violations.append(f"config file not found: {path}")
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        violations.append(f"config file {path} is not valid YAML: {exc}")
        return None
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        violations.append(f"config file {path} must contain a mapping at the top level")
        return None
    return raw


def load_config(
    path: str | Path | None = None,
    env: Mapping[str, str] | ConfigEnvironment | None = None,
) -> TradingConfig:
    """Load and validate a configuration, failing clearly on any violation.

    ``env`` accepts a mapping (for tests) or a ConfigEnvironment. Pass
    ``{}`` to test with a completely empty environment.
    """
    environment = env if isinstance(env, ConfigEnvironment) else ConfigEnvironment(env)
    violations: list[str] = []
    resolved_path = _resolve_config_path(None if path is None else str(path), environment)
    data = _load_yaml(resolved_path, violations)
    if data is None:
        raise ConfigError(violations)
    _apply_env_overrides(data, environment)

    try:
        return TradingConfig.model_validate(data)
    except ValidationError as error:
        for raw in error.errors(include_url=False):
            details = cast("dict[str, Any]", raw)
            location = (
                ".".join(
                    str(part)
                    for part in details["loc"]
                    if str(part) not in {"model_fields", "__root__"}
                )
                or "config"
            )
            message = str(details["msg"])
            if message.startswith("Value error, "):
                message = message[len("Value error, ") :]
            if message.startswith(location) and message[len(location)] in {".", ":"}:
                violations.append(message)
            else:
                violations.append(f"{location}: {message}")
        raise ConfigError(violations) from None
