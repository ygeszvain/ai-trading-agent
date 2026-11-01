"""Shared sanitization rules for model and gateway payloads.

Plan section 9 is explicit: never persist raw credentials, tokens, or
unbounded raw text. This module is the single enforcement point used by
both the research layer and the gateway snapshot layer.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

MAX_REASONABLE_TEXT_CHARS = 32_000

# Patterns that indicate secret-like material; any hit triggers redaction.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|apikey|token|secret|password|passphrase)\b[:\s=]+['\"]?[A-Za-z0-9._\-]{12,}"
    ),
    re.compile(r"\b[A-Za-z0-9+/]{48,}={0,2}\b"),  # long base64/hex blobs
    re.compile(r"\b(?:\d[ -]*){13,19}\b"),  # card-like digit runs
    re.compile(r"(?i)\b(pk_[A-Za-z0-9]{16,}|sk-[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9-]{8,})\b"),
)


def text_digest(text: str) -> str:
    """SHA-256 digest of raw text; the digest is persisted, the text is not."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def redact_secrets(text: str) -> tuple[str, int]:
    """Redact secret-like substrings; returns (clean_text, redaction_count)."""
    redactions = 0
    for pattern in _SECRET_PATTERNS:
        text, count = pattern.subn("[REDACTED]", text)
        redactions += count
    return text, redactions


def sanitize_text(text: str, max_chars: int = MAX_REASONABLE_TEXT_CHARS) -> tuple[str, int]:
    """Enforce the persistence ceiling and strip control characters.

    Returns (sanitized_text, redaction_count). Truncation is a hard ceiling,
    never silent data loss of the audit trail: the caller persists the raw
    digest so the full response can be re-derived from job context only.
    """
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    cleaned, redactions = redact_secrets(cleaned)
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned, redactions


def sanitize_payload(raw: dict[str, Any], allowlist: tuple[str, ...]) -> tuple[dict[str, Any], int]:
    """Keep only allowlisted fields from an untrusted structured payload.

    Field names outside the allowlist are dropped (unlisted gateway/model
    fields never reach the database). String values pass through the text
    sanitizer; numeric/boolean values are kept as-is.
    """
    sanitized: dict[str, Any] = {}
    redactions = 0
    for key in allowlist:
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, str):
            value, count = sanitize_text(value)
            redactions += count
        elif isinstance(value, dict):
            value, count = sanitize_payload(value, tuple(value.keys()))
            redactions += count
        elif not isinstance(value, (int, float, bool)) and value is not None:
            continue  # unsupported types are dropped, never persisted raw
        sanitized[key] = value
    return sanitized, redactions
