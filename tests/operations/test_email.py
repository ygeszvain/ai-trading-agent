import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from sqlalchemy import select

from trading_agent.autonomy.fixtures import NOW
from trading_agent.db.schema import ops_mail, ops_mail_attempts
from trading_agent.operations.email import (
    DeliveryConsent,
    Dispatcher,
    EmailProfile,
    GmailSender,
    Notice,
    enqueue,
)
from trading_agent.supervised.contracts import digest
from trading_agent.supervised.journal import Journal


class Sink:
    def __init__(self, results=None):
        self.calls = []
        self.results = results or ["ACCEPTED"]

    def send(self, notice, message_id):
        self.calls.append(message_id)
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


def setup(engine, *, max_messages=1, results=None):
    profile = EmailProfile(
        enabled=True, sender="owner@example.invalid", recipient="owner@example.invalid"
    )
    consent = DeliveryConsent(
        profile_hash=profile.digest(),
        purpose="FIXTURE",
        scope=digest("scope"),
        approved=True,
        starts_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        max_messages=max_messages,
    )
    clock = [NOW]
    sink = Sink(results)
    worker = Dispatcher(engine, sink, profile, consent, clock=lambda: clock[0])
    with Journal(engine).transaction() as conn:
        notice = Notice(
            domain="FIXTURE",
            scope=digest("scope"),
            incident_hash=digest("incident"),
            code="CONTROL_INCIDENT",
            at=NOW,
        )
        key = enqueue(conn, notice)
        assert enqueue(conn, notice) == key
    return worker, sink, key, clock


def test_durable_attempt_idempotence_ack_and_restart(ops_engine):
    worker, sink, key, clock = setup(ops_engine)
    original = sink.send

    def checked(notice, message_id):
        with ops_engine.connect() as conn:
            assert conn.execute(select(ops_mail.c.status)).scalar_one() == "SENDING"
            assert (
                json.loads(conn.execute(select(ops_mail_attempts.c.document)).scalar_one())[
                    "status"
                ]
                == "STARTED"
            )
        return original(notice, message_id)

    sink.send = checked
    assert worker.send_one(key) == "ACCEPTED"
    assert worker.send_one(key) == "ACCEPTED" and len(sink.calls) == 1
    restarted = Dispatcher(ops_engine, sink, worker.profile, worker.consent, clock=lambda: clock[0])
    assert restarted.send_one(key) == "ACCEPTED" and len(sink.calls) == 1
    restarted.acknowledge(key, digest("owner receipt"))
    assert worker.send_one(key) == "ACKNOWLEDGED"


def test_unclear_send_or_crash_never_retries(ops_engine, monkeypatch):
    worker, sink, key, clock = setup(ops_engine, results=["UNKNOWN"])
    assert worker.send_one(key) == "UNKNOWN" and worker.send_one(key) == "UNKNOWN"
    assert len(sink.calls) == 1
    with Journal(ops_engine).transaction() as conn:
        conn.execute(ops_mail.update().values(status="SENDING"))
    assert worker.send_one(key) == "UNKNOWN" and len(sink.calls) == 1


def test_audit_write_failure_before_network_denies_send(ops_engine, monkeypatch):
    worker, sink, key, clock = setup(ops_engine)
    from sqlalchemy import event

    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO ops_mail_attempts"):
            raise RuntimeError("injected audit outage")

    event.listen(ops_engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError):
            worker.send_one(key)
    finally:
        event.remove(ops_engine, "before_cursor_execute", fail)
    assert sink.calls == []
    with ops_engine.connect() as conn:
        assert conn.execute(select(ops_mail.c.status)).scalar_one() == "PENDING"


def test_definite_rejection_bounded_retry_and_expiry(ops_engine):
    worker, sink, key, clock = setup(ops_engine, results=["RETRYABLE", "ACCEPTED"])
    assert worker.send_one(key) == "RETRYABLE"
    assert worker.send_one(key) == "DENIED"
    clock[0] += timedelta(seconds=30)
    assert worker.send_one(key) == "ACCEPTED" and len(sink.calls) == 2
    with Journal(ops_engine).transaction() as conn:
        other = enqueue(
            conn,
            Notice(
                domain="FIXTURE",
                scope=digest("scope"),
                incident_hash=digest("other"),
                code="CONTROL_INCIDENT",
                at=clock[0],
            ),
        )
    assert worker.send_one(other) == "DENIED"  # one-message owner cap
    clock[0] = worker.consent.expires_at
    assert worker.send_one(other) == "DENIED"


def test_concurrent_workers_cannot_double_send(ops_engine):
    worker, sink, key, clock = setup(ops_engine)
    entered, release = Event(), Event()

    def slow(notice, message_id):
        sink.calls.append(message_id)
        entered.set()
        assert release.wait(5)
        return "ACCEPTED"

    sink.send = slow
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(worker.send_one, key)
        assert entered.wait(5)
        try:
            assert worker.send_one(key) == "UNKNOWN"
        finally:
            release.set()
        assert first.result() == "UNKNOWN"
    assert len(sink.calls) == 1


def test_fixture_and_header_injection_cannot_reach_gmail(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external SMTP attempted")

    monkeypatch.setattr("smtplib.SMTP_SSL", forbidden)
    profile = EmailProfile(
        enabled=True, sender="owner@example.invalid", recipient="owner@example.invalid"
    )
    sender = GmailSender(profile, forbidden)
    notice = Notice(
        domain="FIXTURE",
        scope=digest("scope"),
        incident_hash=digest("x"),
        code="CONTROL_INCIDENT",
        at=NOW,
    )
    assert sender.send(notice, digest("message")) == "REJECTED"
    with pytest.raises(ValueError):
        EmailProfile(
            sender="x@example.invalid\r\nBcc: bad@example.invalid", recipient="x@example.invalid"
        )


def test_post_send_audit_outage_retains_unknown_without_duplicate(ops_engine, monkeypatch):
    worker, sink, key, clock = setup(ops_engine)
    from trading_agent.operations import email

    original = email.record

    def fail(conn, scope, kind, document):
        if kind == "mail_transport_result":
            raise RuntimeError("injected post-send audit outage")
        return original(conn, scope, kind, document)

    with monkeypatch.context() as patch:
        patch.setattr(email, "record", fail)
        with pytest.raises(RuntimeError):
            worker.send_one(key)
    assert len(sink.calls) == 1
    assert worker.send_one(key) == "UNKNOWN" and len(sink.calls) == 1


def test_resolved_failure_requires_new_ack_and_preserves_failed_evidence(ops_engine):
    from trading_agent.operations.email import delivery_health

    worker, sink, key, clock = setup(ops_engine, results=["UNKNOWN"])
    assert worker.send_one(key) == "UNKNOWN"
    worker.resolve_failed(key, digest("owner investigation"))
    with ops_engine.connect() as conn:
        assert not delivery_health(conn, digest("scope"), clock[0], max_ack_age_seconds=3600)
        assert (
            conn.execute(select(ops_mail.c.status).where(ops_mail.c.message_id == key)).scalar_one()
            == "UNKNOWN"
        )
    clock[0] += timedelta(seconds=1)
    consent = worker.consent.changed(starts_at=clock[0], max_messages=2)
    worker = Dispatcher(ops_engine, Sink(), worker.profile, consent, clock=lambda: clock[0])
    with Journal(ops_engine).transaction() as conn:
        new_key = enqueue(
            conn,
            Notice(
                domain="FIXTURE",
                scope=digest("scope"),
                incident_hash=digest("new verification"),
                code="OWNER_EMAIL_TEST",
                at=clock[0],
            ),
        )
    assert worker.send_one(new_key) == "ACCEPTED"
    worker.acknowledge(new_key, digest("new owner receipt"))
    with ops_engine.connect() as conn:
        assert delivery_health(conn, digest("scope"), clock[0], max_ack_age_seconds=3600)


def test_receipt_recorded_during_slow_transport_is_never_overwritten(ops_engine):
    worker, sink, key, clock = setup(ops_engine)

    def acknowledged_while_sending(notice, message_id):
        assert worker.send_one(message_id) == "UNKNOWN"
        worker.acknowledge(message_id, digest("owner verified inbox during delayed result"))
        return "ACCEPTED"

    sink.send = acknowledged_while_sending
    assert worker.send_one(key) == "ACKNOWLEDGED"
    with ops_engine.connect() as conn:
        assert conn.execute(select(ops_mail.c.status)).scalar_one() == "ACKNOWLEDGED"


def test_email_health_and_consent_cannot_cross_runs(ops_engine):
    from trading_agent.operations.email import delivery_health

    worker, sink, key, clock = setup(ops_engine)
    assert worker.send_one(key) == "ACCEPTED"
    worker.acknowledge(key, digest("owner receipt"))
    with Journal(ops_engine).transaction() as conn:
        assert delivery_health(conn, digest("scope"), clock[0], max_ack_age_seconds=300)
        assert not delivery_health(
            conn, digest("scope"), clock[0], max_ack_age_seconds=300, run_id="different-run"
        )
        other = enqueue(
            conn,
            Notice(
                domain="FIXTURE",
                scope=digest("scope"),
                run_id="different-run",
                incident_hash=digest("different run incident"),
                code="CONTROL_INCIDENT",
                at=clock[0],
            ),
        )
    assert worker.send_one(other) == "DENIED" and len(sink.calls) == 1
