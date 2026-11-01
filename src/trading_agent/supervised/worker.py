"""Isolated MOCK executor process. stdin is a bounded fixture script, never an executor socket."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from .contracts import Digest, Holding, Identifier, Intent, Record, Signed
from .executor import MockControls, MockExecutor
from .fake import FakeTransport, Observation
from .journal import Journal


class ResumeCommand(Record):
    action: Literal["resume"]
    proof: Signed


class ApproveCommand(Record):
    action: Literal["approve"]
    intent: Intent
    proof: Signed


class DispatchCommand(Record):
    action: Literal["dispatch"]
    intent: Intent
    approval_id: Identifier


class ObserveCommand(Record):
    action: Literal["fixture_broker_observation"]
    intent_id: Identifier
    observation: Observation


class ReconcileCommand(Record):
    action: Literal["fixture_account_reconciliation"]
    cash: Annotated[str, Field(pattern=r"^\d+(\.\d{1,8})?$")]
    holdings: tuple[Holding, ...]


Command = Annotated[
    ResumeCommand | ApproveCommand | DispatchCommand | ObserveCommand | ReconcileCommand,
    Field(discriminator="action"),
]


class Script(Record):
    domain: Literal["M6_MOCK_ONLY"]
    account_key: Digest
    boot_id: Identifier
    at: AwareDatetime
    commands: tuple[Command, ...] = Field(max_length=12)


def run(path: Path, script: Script) -> dict[str, object]:
    from decimal import Decimal

    if path.is_symlink() or not path.is_file() or path.suffix != ".sqlite":
        raise ValueError("existing private fixture SQLite journal required")
    engine = create_engine(URL.create("sqlite", database=str(path.resolve())))
    journal = Journal(engine)
    fake = FakeTransport(account_key=script.account_key)
    executor = MockExecutor(journal, fake, boot_id=script.boot_id, clock=lambda: script.at)
    controls = MockControls(journal)
    executor.startup(script.account_key, now=script.at)
    for command in script.commands:
        if isinstance(command, ResumeCommand):
            controls.resume(command.proof, now=script.at)
        elif isinstance(command, ApproveCommand):
            controls.approve(command.intent, command.proof, now=script.at)
        elif isinstance(command, DispatchCommand):
            executor.dispatch(command.intent, command.approval_id, now=script.at)
        elif isinstance(command, ObserveCommand):
            fake.observations[command.intent_id] = command.observation
            executor.reconcile_order(script.account_key, command.intent_id, now=script.at)
        elif isinstance(command, ReconcileCommand):
            executor.reconcile_account(
                script.account_key,
                cash=Decimal(command.cash),
                holdings=command.holdings,
                now=script.at,
            )
    with journal.transaction() as conn:
        state = journal.state(conn, script.account_key)
        result = {
            "pid": os.getpid(),
            "domain": "M6_MOCK_ONLY",
            "authority": "LIVE_NOT_AUTHORIZED",
            "actual_dispatch_allowed": False,
            "transport_calls": fake.calls,
            "state_hash": state.digest(),
            "paused": state.paused,
            "resumed": state.resumed,
        }
    engine.dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline fixture worker; no real transport or authorization"
    )
    parser.add_argument("--fixture-db", type=Path, required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(64001)
        if len(raw) > 64000:
            raise ValueError("fixture script exceeds byte limit")
        result = run(args.fixture_db, Script.model_validate_json(raw))
        print(json.dumps(result, sort_keys=True))
    except Exception as error:
        print(
            json.dumps(
                {
                    "authority": "LIVE_NOT_AUTHORIZED",
                    "error_class": type(error).__name__,
                    "detail": "MOCK script denied; inspect journal and reconcile before retry",
                }
            )
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
