"""Decimal money helpers.

All cash, quantity, price, fee, and limit values are Decimal. Floats are
accepted at the configuration boundary only for convenience and are
converted via their shortest string representation (e.g. 0.05 -> "0.05").
Numeric feature computation may use floats; conversion back to Decimal is
required before money calculations (build plan section 6).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

_MAX_PRECISION = 28


def parse_money(value: Any, *, field: str, allow_negative: bool = False) -> Decimal:
    """Parse a configuration value into a Decimal, failing clearly.

    Rejects NaN/Infinity, non-numeric types, and (unless ``allow_negative``)
    negative values. Ints and short decimal strings are exact.
    """
    if isinstance(value, bool):
        raise ValueError(f"{field}: expected a number, got boolean {value!r}")
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"{field}: non-finite float is not a valid money/limit value")
        text = repr(value)
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, Decimal):
        return value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field}: empty value")
    else:
        raise ValueError(f"{field}: unsupported type {type(value).__name__}")
    try:
        with localcontext() as ctx:
            ctx.prec = _MAX_PRECISION
            parsed = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{field}: {text!r} is not a valid decimal number") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field}: non-finite value {text!r}")
    if not allow_negative and parsed < 0:
        raise ValueError(f"{field}: negative value {text} is not permitted")
    return parsed


def parse_fraction(value: Any, *, field: str) -> Decimal:
    """Parse a fraction-of-NAV style value; must be finite and in [0, 1]."""
    parsed = parse_money(value, field=field, allow_negative=True)
    if parsed < 0 or parsed > 1:
        raise ValueError(f"{field}: fraction {parsed} must be between 0 and 1")
    return parsed


def format_money(value: Decimal) -> str:
    """Canonical string form for display/serialization (exact, no rounding)."""
    return str(value.normalize())
