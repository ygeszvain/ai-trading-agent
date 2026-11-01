"""Append-only evidence with the caller's existing financial transaction."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from ..db.schema import ops_records
from ..supervised.contracts import digest


def record(conn: Connection, scope: str, kind: str, document: dict[str, Any]) -> str:
    key = digest({"scope": scope, "kind": kind, "document": document})
    old = conn.execute(select(ops_records).where(ops_records.c.record_id == key)).first()
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"))
    if old is None:
        conn.execute(
            ops_records.insert().values(record_id=key, scope=scope, kind=kind, document=raw)
        )
    elif old.document != raw or old.scope != scope or old.kind != kind:
        raise ValueError("operational evidence conflict")
    return key
