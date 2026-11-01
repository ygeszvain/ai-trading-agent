from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from trading_agent.autonomy.fixtures import NOW
from trading_agent.db.schema import ops_records
from trading_agent.operations.reconciliation import (
    COLLECTIONS,
    Inventory,
    LedgerView,
    OpenOrder,
    Position,
    compare,
    persist,
)
from trading_agent.supervised.contracts import digest


def views():
    positions = (
        Position(asset_class="equity", instrument="MOCK_ETF", quantity="2"),
        Position(asset_class="crypto", instrument="MOCK_LEGACY", quantity=".0235"),
    )
    observed = Inventory(
        account_key=digest("account"),
        run_id="run",
        mode="simulation",
        currency="USD",
        schema_hash=digest("schema"),
        source="FIXTURE",
        started_at=NOW,
        completed_at=NOW,
        complete=True,
        cash="979.99",
        unleveraged_buying_power="979.99",
        positions=positions,
        orders=(),
        collections=tuple(sorted(COLLECTIONS)),
    )
    ledger = LedgerView(
        account_key=observed.account_key,
        run_id="run",
        mode="simulation",
        cash="979.99",
        positions=positions,
        orders=(),
        audit_healthy=True,
    )
    return observed, ledger


def test_exact_account_wide_snapshot_does_not_imply_settled_funds_and_persists_failures(ops_engine):
    observed, ledger = views()
    result = compare(observed, ledger, now=NOW, approved_schema=observed.schema_hash)
    assert (
        result.consistent
        and not result.settled_funds_verified
        and not result.actual_dispatch_allowed
    )
    with ops_engine.begin() as conn:
        first = persist(conn, observed, ledger, result)
        assert persist(conn, observed, ledger, result) == first
        changed = observed.changed(cash=Decimal("900"))
        failure = compare(changed, ledger, now=NOW, approved_schema=observed.schema_hash)
        persist(conn, changed, ledger, failure)
    with ops_engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(ops_records)
                .where(ops_records.c.kind == "reconciliation")
            ).scalar_one()
            == 2
        )
    assert ledger.cash == Decimal("979.99")  # no correction/deposit is silently adopted


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"account_key": digest("other")}, "scope_mismatch"),
        ({"mode": "shadow"}, "scope_mismatch"),
        ({"complete": False}, "incomplete_observation"),
        ({"collections": ()}, "incomplete_observation"),
        ({"schema_hash": digest("drift")}, "schema_drift"),
        ({"cash": None}, "cash_unknown"),
        ({"completed_at": NOW + timedelta(seconds=1)}, "stale_or_future_observation"),
        ({"started_at": NOW - timedelta(seconds=6)}, "inconsistent_snapshot_window"),
        ({"positions": ()}, "position_difference"),
        ({"pending_approvals": (digest("pending"),)}, "pending_broker_approval"),
    ],
)
def test_incomplete_stale_scope_manual_activity_or_approval_cannot_pass(change, reason):
    observed, ledger = views()
    result = compare(
        observed.changed(**change), ledger, now=NOW, approved_schema=observed.schema_hash
    )
    assert not result.consistent and reason in result.differences


def test_exact_precision_and_unknown_orders_are_not_suppressed():
    observed, ledger = views()
    delta = observed.positions[1].changed(quantity=Decimal(".023500000000000001"))
    assert not compare(
        observed.changed(positions=(observed.positions[0], delta)),
        ledger,
        now=NOW,
        approved_schema=observed.schema_hash,
    ).consistent
    order = OpenOrder(
        order_key=digest("order"),
        instrument="MOCK_ETF",
        side="buy",
        remaining="1",
        status="unknown",
    )
    result = compare(
        observed.changed(orders=(order,)),
        ledger.changed(orders=(order,)),
        now=NOW,
        approved_schema=observed.schema_hash,
    )
    assert "unresolved_order_state" in result.differences
    for value in (float("nan"), float("inf"), 1.2, True, "NaN"):
        with pytest.raises(ValueError):
            observed.changed(cash=value)
    with pytest.raises(ValueError):
        observed.changed(positions=(observed.positions[0], observed.positions[0]))


def test_forged_passing_comparison_cannot_be_persisted(ops_engine):
    observed, ledger = views()
    wrong = observed.changed(cash=Decimal("10"))
    result = compare(wrong, ledger, now=NOW, approved_schema=observed.schema_hash)
    with ops_engine.begin() as conn, pytest.raises(ValueError, match="forged"):
        persist(conn, wrong, ledger, result.changed(consistent=True, differences=()))
