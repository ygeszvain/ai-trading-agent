"""PUBLIC synthetic owner fixture issuer. Never loaded by research or normal setup."""

import hashlib
import hmac

from ..supervised.contracts import Record
from .contracts import MOCK_OWNER_KEY, Signed


def sign_fixture(record: Record) -> Signed:
    payload = record.model_dump_json()
    return Signed(
        role="fixture_owner",
        payload_json=payload,
        signature=hmac.new(MOCK_OWNER_KEY, payload.encode(), hashlib.sha256).hexdigest(),
    )
