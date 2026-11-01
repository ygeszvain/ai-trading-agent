"""A child-process, network-free M6 demonstration; no activation function exists."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from .contracts import Fill, Holding, mock_sign
from .fixtures import KEY, NOW, approval_fixture, intent_fixture, resume_fixture, state_fixture
from .journal import Journal
from .package import unsigned_package
from .worker import Script


def run_demo(root: Path) -> dict[str, Any]:
    # A new directory preserves every prior successful and failed demonstration.
    target = root / ("mock-" + uuid.uuid4().hex)
    target.mkdir(parents=True, mode=0o700)
    db = target / "journal.sqlite"
    descriptor = os.open(db, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    engine = create_engine(URL.create("sqlite", database=str(db.resolve())))
    journal = Journal(engine)
    journal.create_fixture_schema()
    state = state_fixture()
    journal.seed(state, NOW)
    intent = intent_fixture(state)
    approval = approval_fixture(state, intent)
    startup = state.changed(
        boot_id="fixture-child", revision=state.revision + 1, resumed=False, paused=True
    )
    fill = Fill(
        fill_id="fixture-fill-1",
        order_id=intent.intent_id,
        account_key=KEY,
        instrument=intent.instrument,
        side="buy",
        quantity=Decimal(1),
        price=Decimal(5),
        fee=Decimal(".005"),
        at=NOW,
    )
    holding = Holding(
        instrument=intent.instrument, quantity=Decimal(2), average_cost=Decimal("5.005")
    )
    script = Script.model_validate(
        {
            "domain": "M6_MOCK_ONLY",
            "account_key": KEY,
            "boot_id": "fixture-child",
            "at": NOW,
            "commands": (
                {"action": "resume", "proof": mock_sign(resume_fixture(startup))},
                {"action": "approve", "intent": intent, "proof": mock_sign(approval)},
                {"action": "dispatch", "intent": intent, "approval_id": approval.approval_id},
                {
                    "action": "fixture_broker_observation",
                    "intent_id": intent.intent_id,
                    "observation": {
                        "status": "acknowledged",
                        "broker_order_id": "mock-order:" + intent.intent_id,
                        "fills": (fill,),
                    },
                },
                {
                    "action": "fixture_broker_observation",
                    "intent_id": intent.intent_id,
                    "observation": {
                        "status": "filled",
                        "broker_order_id": "mock-order:" + intent.intent_id,
                        "fills": (fill, fill.changed(fill_id="fixture-fill-2")),
                    },
                },
                {
                    "action": "fixture_account_reconciliation",
                    "cash": "989.99",
                    "holdings": (holding,),
                },
            ),
        }
    )
    (target / "fixture-script.json").write_text(script.model_dump_json(indent=2) + "\n")
    completed = subprocess.run(
        [sys.executable, "-m", "trading_agent.supervised.worker", "--fixture-db", str(db)],
        input=script.model_dump_json(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "SYSTEMROOT", "TMPDIR", "PYTHONPATH", "VIRTUAL_ENV"}
        },
    )
    (target / "worker-output.txt").write_text(completed.stdout)
    if completed.returncode:
        # No automatic retry after any uncertain child result.
        raise RuntimeError("mock child failed; journal and script preserved for review")
    child = json.loads(completed.stdout)
    assert child["pid"] != os.getpid() and child["authority"] == "LIVE_NOT_AUTHORIZED"
    with journal.transaction() as conn:
        state = journal.state(conn, KEY)
        order = journal.order(conn, intent.intent_id, KEY)
        assert (
            state.cash == Decimal("989.99")
            and state.reserved_cash == 0
            and order.filled_quantity == 2
        )
        assert state.reconciliation.status == "healthy" and not state.resumed
    result = {
        "domain": "M6_MOCK_ONLY",
        "authority": "LIVE_NOT_AUTHORIZED",
        "actual_dispatch_allowed": False,
        "software_evidence": "CODE_PASS: bounded child-process fixture only",
        "integration_evidence": "EXTERNAL_VALIDATION_PENDING",
        "investment_evidence": "EXTERNAL_VALIDATION_PENDING",
        "parent_pid": os.getpid(),
        "worker": child,
        "intent": intent.model_dump(mode="json"),
        "approval": approval.model_dump(mode="json"),
        "order": order.model_dump(mode="json"),
        "cash": str(state.cash),
        "reserved_cash": str(state.reserved_cash),
        "explicit_resume_required": True,
        "journal": str(db.resolve()),
        "unsigned_package": "activation-package.unsigned.json",
    }
    (target / "activation-package.unsigned.json").write_text(
        json.dumps(unsigned_package(), indent=2) + "\n"
    )
    (target / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    engine.dispose()
    return result
