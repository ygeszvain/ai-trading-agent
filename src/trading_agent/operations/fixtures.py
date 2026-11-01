"""Public synthetic mail material; cannot enable Gmail or authenticate an owner."""

from datetime import datetime, timedelta

from sqlalchemy.engine import Engine

from ..supervised.contracts import digest
from ..supervised.journal import Journal
from .email import DeliveryConsent, Dispatcher, EmailProfile, Notice, Status, enqueue


def acknowledge_fixture_channel(
    engine: Engine, scope: str, now: datetime, *, run_id: str = "m7-demo"
) -> None:
    class FixtureSink:
        def send(self, notice: Notice, message_id: str) -> Status:
            if notice.domain != "FIXTURE":
                return "REJECTED"
            return "ACCEPTED"

    profile = EmailProfile(
        enabled=True, sender="owner@example.invalid", recipient="owner@example.invalid"
    )
    consent = DeliveryConsent(
        profile_hash=profile.digest(),
        scope=scope,
        run_id=run_id,
        purpose="FIXTURE",
        approved=True,
        starts_at=now,
        expires_at=now + timedelta(hours=1),
    )
    with Journal(engine).transaction() as conn:
        key = enqueue(
            conn,
            Notice(
                domain="FIXTURE",
                scope=scope,
                run_id=run_id,
                incident_hash=digest("fixture-email-verification"),
                code="OWNER_EMAIL_TEST",
                at=now,
            ),
        )
    worker = Dispatcher(engine, FixtureSink(), profile, consent, clock=lambda: now)
    assert worker.send_one(key) == "ACCEPTED"
    worker.acknowledge(key, digest("PUBLIC_FIXTURE_OWNER_ACK_NOT_REAL_DELIVERY"))
