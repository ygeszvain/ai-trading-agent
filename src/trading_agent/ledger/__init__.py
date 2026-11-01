"""The durable money ledger (build plan section 16).

The ledger is the single authoritative accounting record. It is append-only:
every cash/position movement is an immutable ``ledger_events`` row keyed by a
deterministic ``event_key`` so replaying any event is a no-op (idempotent).
History is never rewritten; corrections are linked, new rows.
"""

from .ledger import Ledger, LedgerInvariantError

__all__ = ["Ledger", "LedgerInvariantError"]
