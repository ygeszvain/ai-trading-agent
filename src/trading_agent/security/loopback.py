"""Loopback-only URL enforcement for inference and broker endpoints.

Accidental cloud inference is a plan violation; every network-capable
adapter re-validates its endpoint here, independently of configuration
validation, at request time (defense in depth).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def is_loopback_url(url: str) -> bool:
    """True when the URL targets a loopback address on a non-TLS port or TLS loopback."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified
