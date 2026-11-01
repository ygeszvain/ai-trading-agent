"""End-of-session reconciliation (plan section 14: reconciliation and
exclusive ownership).

Broker-confirmed state is authoritative for holdings and fills. The local
ledger must preserve any difference as an explicit, persistent
``reconciliation_runs`` record — never by silently rewriting history. In the
M1 simulator the venue *is* the broker, so the comparison is between the
venue's own books and the application ledger; the mechanism, statuses, and
persistence are identical to what M4 will use against the official gateway.

Statuses:
- ``consistent``: ledger and venue agree (within rounding tolerance).
- ``needs-review``: a difference exists; new risk must be blocked until an
  owner (or M3's automated resolution) investigates.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..contracts.orders import RuntimeStatus
from ..db.schema import reconciliation_runs, reservations
from ..ledger import Ledger
from ..money import round_money
from .simulator import SimulatorBrokerAdapter

_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class ReconciliationResult:
    status: str  # "consistent" | "needs-review"
    differences: dict[str, str] = field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ReconciliationService:
    """Runs session-end reconciliation and persists the outcome."""

    def __init__(self, session: Session, run_id: str, account_alias: str) -> None:
        self._session = session
        self._run_id = run_id
        self._account_alias = account_alias

    def run_session_end(
        self,
        at: datetime,
        *,
        strategy_ledger: Ledger,
        adapter: SimulatorBrokerAdapter,
    ) -> ReconciliationResult:
        venue = adapter.venue_state(at)
        differences: dict[str, str] = {}

        cash_delta = round_money(strategy_ledger.cash - venue.cash)
        if abs(cash_delta) > _TOLERANCE:
            differences["cash"] = (
                f"ledger {strategy_ledger.cash} vs venue {venue.cash} (delta {cash_delta})"
            )

        for instrument_id in sorted(set(strategy_ledger.positions) | set(venue.positions)):
            ledger_qty = strategy_ledger.position(instrument_id).quantity
            venue_qty = venue.positions.get(instrument_id, Decimal("0"))
            delta = round_money(ledger_qty - venue_qty)
            if abs(delta) > Decimal("0"):
                differences[f"position:{instrument_id}"] = (
                    f"ledger {ledger_qty} vs venue {venue_qty} (delta {delta})"
                )

        # Reservations must be resolved by now: any still active is a
        # discrepancy (a crash mid-session would have rolled back).
        open_res = self._session.execute(
            select(reservations.c.reservation_id).where(
                reservations.c.run_id == self._run_id,
                reservations.c.status == "active",
            )
        ).all()
        if open_res:
            differences["open_reservations"] = (
                f"{len(open_res)} reservation(s) still active at session end"
            )

        status = "needs-review" if differences else "consistent"
        reconciliation_id = hashlib.sha256(
            f"{self._run_id}|recon|{at.isoformat()}".encode()
        ).hexdigest()[:32]
        self._session.execute(
            reconciliation_runs.insert().values(
                reconciliation_id=reconciliation_id,
                run_id=self._run_id,
                session_date=at.date().isoformat(),
                status=status,
                differences=json.dumps(differences),
                started_at=at,
                completed_at=at,
            )
        )
        return ReconciliationResult(
            status=status,
            differences=differences,
            started_at=at,
            completed_at=at,
        )

    def healthy(self) -> bool | None:
        """None = no reconciliation data yet; the activation gate treats that as unmet."""
        status = (
            self._session.execute(
                select(reconciliation_runs.c.status)
                .where(reconciliation_runs.c.run_id == self._run_id)
                .order_by(reconciliation_runs.c.completed_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if status is None:
            return None
        return status == "consistent"

    def runtime_status(self, active_strategy_versions: tuple[str, ...] = ()) -> RuntimeStatus:
        healthy = self.healthy()
        return RuntimeStatus(
            last_reconciliation_status=None
            if healthy is None
            else ("consistent" if healthy else "needs-review"),
            active_strategy_versions=active_strategy_versions,
        )
