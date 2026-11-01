"""Transactional M6 mock journal. No broker credentials or real account data belong here."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import Table, select
from sqlalchemy.engine import Connection, Engine

from ..db.schema import (
    M6_TABLES as TABLES,
)
from ..db.schema import metadata
from .contracts import Order, Signed, State
from .readiness import config_for


class Denied(ValueError):
    """Classified denial; no free-form provider errors are logged."""


class Journal:
    def __init__(self, engine: Engine, *, tables: tuple[Table, ...] = TABLES) -> None:
        self.engine = engine
        self.tables = tables
        self.accounts, self.approvals, self.orders, self.fills, self.audit = tables

    def create_fixture_schema(self) -> None:
        """Only tests/demo call this, never normal website startup."""
        metadata.create_all(self.engine, tables=list(self.tables))

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.engine.connect() as conn:
            if conn.dialect.name == "sqlite":
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                conn.begin()
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def state(self, conn: Connection, key: str) -> State:
        query = select(self.accounts.c.document).where(self.accounts.c.account_key == key)
        if conn.dialect.name == "postgresql":
            query = query.with_for_update()
        raw = conn.execute(query).scalar_one_or_none()
        if raw is None:
            raise Denied("account state missing")
        state = State.model_validate_json(raw)
        if state.account_key != key:
            raise Denied("stored account binding mismatch")
        return state

    def save(self, conn: Connection, state: State) -> State:
        config_for(state)
        state = state.changed(revision=state.revision + 1)
        conn.execute(
            self.accounts.update()
            .where(self.accounts.c.account_key == state.account_key)
            .values(document=state.model_dump_json())
        )
        return state

    def seed(self, state: State, at: datetime) -> None:
        config_for(state)
        with self.transaction() as conn:
            conn.execute(
                self.accounts.insert().values(
                    account_key=state.account_key, document=state.model_dump_json()
                )
            )
            self.event(
                conn,
                state,
                at,
                "fixture_created",
                {"domain": state.domain, "state_hash": state.digest()},
            )

    def event(
        self, conn: Connection, state: State, at: datetime, kind: str, payload: dict[str, Any]
    ) -> None:
        conn.execute(
            self.audit.insert().values(
                account_key=state.account_key,
                run_id=state.run_id,
                at=at.isoformat(),
                event_type=kind,
                payload=json.dumps(payload, sort_keys=True),
            )
        )

    def order(self, conn: Connection, intent_id: str, key: str) -> Order:
        raw = conn.execute(
            select(self.orders.c.document).where(
                self.orders.c.intent_id == intent_id, self.orders.c.account_key == key
            )
        ).scalar_one_or_none()
        if raw is None:
            raise Denied("order not found in account")
        order = Order.model_validate_json(raw)
        if order.intent.account_key != key or order.intent.intent_id != intent_id:
            raise Denied("stored order binding mismatch")
        return order

    def save_order(self, conn: Connection, order: Order) -> None:
        conn.execute(
            self.orders.update()
            .where(
                self.orders.c.intent_id == order.intent.intent_id,
                self.orders.c.account_key == order.intent.account_key,
            )
            .values(document=order.model_dump_json())
        )

    def account_orders(self, conn: Connection, key: str) -> list[Order]:
        raw_records: list[str] = list(
            conn.execute(
                select(self.orders.c.document).where(self.orders.c.account_key == key)
            ).scalars()
        )
        return [Order.model_validate_json(raw) for raw in raw_records]

    def approval(self, conn: Connection, key: str, approval_id: str) -> tuple[Signed, bool, bool]:
        row = conn.execute(
            select(self.approvals).where(
                self.approvals.c.approval_id == approval_id, self.approvals.c.account_key == key
            )
        ).first()
        if row is None:
            raise Denied("approval missing or outside account")
        return Signed.model_validate_json(row.document), bool(row.consumed), bool(row.revoked)
