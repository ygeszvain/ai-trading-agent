"""CSV cells must not turn untrusted labels into spreadsheet formulas."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from typing import Any, TextIO

from ..research.sanitization import redact_secrets


def redacted_evidence(value: Any) -> Any:
    """Sanitize free-form read evidence; financial columns are serialized separately."""
    if isinstance(value, str):
        return redact_secrets(value)[0]
    if isinstance(value, list):
        return [redacted_evidence(item) for item in value]
    if isinstance(value, dict):
        private = {
            "authorization",
            "access_token",
            "refresh_token",
            "owner_token",
            "session_secret",
            "account_number",
            "api_key",
            "password",
            "secret",
            "token",
        }
        return {
            key: "[REDACTED]" if str(key).lower() in private else redacted_evidence(item)
            for key, item in value.items()
        }
    return value


def safe_csv_cell(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    try:
        if value == value.strip() and Decimal(value).is_finite():
            return value
    except InvalidOperation:
        pass
    value = redact_secrets(value)[0]
    if value[0] in "\t\r\n" or value.lstrip().startswith(("=", "+", "-", "@")):
        try:
            if value == value.strip() and Decimal(value).is_finite():
                return value  # a negative financial amount is a number, not a formula
        except InvalidOperation:
            pass
        return "'" + value
    return value


class SafeCsvWriter:
    def __init__(self, handle: TextIO) -> None:
        self._writer = csv.writer(handle)

    def writerow(self, values: Any) -> Any:
        return self._writer.writerow([safe_csv_cell(value) for value in values])
