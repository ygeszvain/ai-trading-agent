"""Security primitives shared across adapters (plan section 9)."""

from __future__ import annotations

from .loopback import is_loopback_url

__all__ = ["is_loopback_url"]
