"""Durable, bounded incident mail; SMTP acceptance is not inbox delivery.

Only owner-runtime code constructs Gmail transport. Mock incidents can never
leave through Gmail; timeout after DATA is UNKNOWN and is never blindly retried.
"""

from __future__ import annotations

import json
import re
import smtplib
import ssl
from collections.abc import Callable
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Literal, Protocol, Self

from pydantic import AwareDatetime, Field, SecretStr, model_validator
from sqlalchemy import select
from sqlalchemy.engine import Engine

from ..db.schema import ops_mail, ops_mail_attempts, ops_records
from ..supervised.contracts import Digest, Identifier, Record, digest
from ..supervised.journal import Journal
from .journal import record

Code = Literal[
    "CONTROL_INCIDENT",
    "CLOSEOUT_BLOCKED",
    "RECONCILIATION_FAILED",
    "MONITOR_MISSING",
    "OWNER_EMAIL_TEST",
]
Status = Literal["ACCEPTED", "RETRYABLE", "REJECTED", "UNKNOWN"]


class Notice(Record):
    domain: Literal["FIXTURE", "OPERATIONAL_NOTICE", "OWNER_EMAIL_TEST"]
    scope: Digest
    incident_hash: Digest
    run_id: Identifier = "operations"
    code: Code
    at: AwareDatetime


class EmailProfile(Record):
    enabled: bool = False
    sender: str = Field(max_length=254)
    recipient: str = Field(max_length=254)
    keychain_service: Literal["ai-trading-agent.gmail-smtp"] = "ai-trading-agent.gmail-smtp"

    @model_validator(mode="after")
    def safe(self) -> Self:
        for address in (self.sender, self.recipient):
            if not re.fullmatch(
                r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", address
            ):
                raise ValueError("invalid single mail address")
        if self.sender != self.recipient:
            raise ValueError("this owner-selected profile requires the same sender and recipient")
        return self


class DeliveryConsent(Record):
    profile_hash: Digest
    scope: Digest | None = None
    run_id: Identifier = "operations"
    purpose: Literal["OWNER_EMAIL_TEST", "OPERATIONAL_NOTICE", "FIXTURE"]
    approved: bool = False
    starts_at: AwareDatetime
    expires_at: AwareDatetime
    max_attempts: int = Field(default=3, ge=1, le=3)
    max_messages: int = Field(default=1, ge=1, le=100)
    acknowledgement_seconds: int = Field(default=300, ge=30, le=3600)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if self.expires_at <= self.starts_at:
            raise ValueError("invalid mail consent interval")
        if self.purpose == "OWNER_EMAIL_TEST" and self.max_messages != 1:
            raise ValueError("owner test is one message only")
        return self


def render(profile: EmailProfile, notice: Notice, message_id: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = profile.sender
    message["To"] = profile.recipient
    message["Message-ID"] = "<" + message_id + "@ai-trading-agent.local>"
    message["Subject"] = "[AI Trading Agent] " + notice.code
    message.set_content(
        "Operational notification; this message grants no trading authority.\n"
        f"Event: {notice.code}\nIncident reference: {notice.incident_hash}\n"
        f"Observed at: {notice.at.isoformat()}\n"
        "Review the protected local incident record and respond through the owner procedure.\n"
        "Pause is not confirmation of cancellation or liquidation.\n"
        "No account number, broker response or credential is included.\n"
    )
    return message


class Sender(Protocol):
    def send(self, notice: Notice, message_id: str) -> Status: ...


class GmailSender:
    """Pinned implicit-TLS SMTP; password supplier belongs to owner runtime only."""

    def __init__(self, profile: EmailProfile, password: Callable[[], SecretStr]) -> None:
        self.profile, self.password = profile, password

    def send(self, notice: Notice, message_id: str) -> Status:
        if notice.domain == "FIXTURE" or not self.profile.enabled:
            return "REJECTED"
        data_started = False
        smtp_accepted = False
        try:
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15, context=context) as smtp:
                smtp.login(self.profile.sender, self.password().get_secret_value())
                data_started = True
                refused = smtp.send_message(render(self.profile, notice, message_id))
                smtp_accepted = not refused
                return "REJECTED" if refused else "ACCEPTED"
        except smtplib.SMTPAuthenticationError:
            return "REJECTED"
        except (smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as error:
            return "RETRYABLE" if 400 <= error.smtp_code < 500 else "REJECTED"
        except smtplib.SMTPRecipientsRefused as error:
            return (
                "RETRYABLE"
                if all(400 <= v[0] < 500 for v in error.recipients.values())
                else "REJECTED"
            )
        except (OSError, smtplib.SMTPException, ValueError):
            return "ACCEPTED" if smtp_accepted else "UNKNOWN" if data_started else "RETRYABLE"


def enqueue(conn: object, notice: Notice) -> str:
    from sqlalchemy.engine import Connection

    if not isinstance(conn, Connection):
        raise TypeError("existing transaction required")
    key = digest(
        {
            "scope": notice.scope,
            "incident": notice.incident_hash,
            "run_id": notice.run_id,
            "code": notice.code,
        }
    )
    prior = conn.execute(select(ops_mail).where(ops_mail.c.message_id == key)).first()
    if prior is None:
        document = {
            "notice": notice.model_dump(mode="json"),
            "attempts": 0,
            "next_at": notice.at.isoformat(),
            "accepted_at": None,
            "acknowledged_at": None,
            "ack_deadline": None,
        }
        conn.execute(
            ops_mail.insert().values(
                message_id=key,
                scope=notice.scope,
                status="PENDING",
                revision=0,
                document=json.dumps(document),
            )
        )
        record(
            conn,
            notice.scope,
            "mail_queued",
            {"message_id": key, "notice": notice.model_dump(mode="json")},
        )
    elif Notice.model_validate_json(json.dumps(json.loads(prior.document)["notice"])) != notice:
        raise ValueError("conflicting incident mail evidence")
    return key


class Dispatcher:
    def __init__(
        self,
        engine: Engine,
        sender: Sender,
        profile: EmailProfile,
        consent: DeliveryConsent,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self.engine, self.sender, self.profile, self.consent, self.clock = (
            engine,
            sender,
            profile,
            consent,
            clock,
        )
        if isinstance(sender, GmailSender) and sender.profile != profile:
            raise ValueError("sender/profile binding mismatch")
        self.journal = Journal(engine)
        with self.journal.transaction() as conn:
            self.grant_id = record(
                conn, consent.profile_hash, "mail_delivery_consent", consent.model_dump(mode="json")
            )

    def send_one(self, message_id: str) -> str:
        now = self.clock()
        with self.journal.transaction() as conn:
            conn.execute(
                select(ops_records.c.record_id)
                .where(ops_records.c.record_id == self.grant_id)
                .with_for_update()
            ).one()
            row = conn.execute(
                select(ops_mail).where(ops_mail.c.message_id == message_id).with_for_update()
            ).one()
            doc = json.loads(row.document)
            notice = Notice.model_validate_json(json.dumps(doc["notice"]))
            if row.status in {"ACCEPTED", "ACKNOWLEDGED", "UNKNOWN", "REJECTED"}:
                return str(row.status)
            if row.status == "SENDING":
                # A prior process may have handed DATA to SMTP. Never automatically repeat.
                conn.execute(
                    ops_mail.update()
                    .where(ops_mail.c.message_id == message_id)
                    .values(status="UNKNOWN")
                )
                record(conn, row.scope, "mail_recovery_unknown", {"message_id": message_id})
                return "UNKNOWN"
            if (
                not self.profile.enabled
                or not self.consent.approved
                or self.consent.profile_hash != self.profile.digest()
                or self.consent.purpose != notice.domain
                or self.consent.run_id != notice.run_id
                or notice.scope != (self.consent.scope or self.profile.digest())
                or not self.consent.starts_at <= now < self.consent.expires_at
                or datetime.fromisoformat(doc["next_at"]) > now
            ):
                return "DENIED"
            consent_key = self.consent.digest()
            used: list[str] = list(
                conn.execute(
                    select(ops_mail_attempts.c.document)
                    .where(ops_mail_attempts.c.consent_hash == consent_key)
                    .limit(301)
                ).scalars()
            )
            consent_key = self.consent.digest()
            used_ids = {
                json.loads(r)["message_id"]
                for r in used
                if json.loads(r)["consent_hash"] == consent_key
            }
            if (message_id not in used_ids and len(used_ids) >= self.consent.max_messages) or doc[
                "attempts"
            ] >= self.consent.max_attempts:
                return "DENIED"
            doc["attempts"] += 1
            changed = conn.execute(
                ops_mail.update()
                .where(
                    ops_mail.c.message_id == message_id,
                    ops_mail.c.revision == row.revision,
                    ops_mail.c.status == row.status,
                )
                .values(status="SENDING", revision=row.revision + 1, document=json.dumps(doc))
            )
            if changed.rowcount != 1:
                return "DENIED"
            attempt_id = digest({"message": message_id, "attempt": doc["attempts"]})
            attempt = {
                "message_id": message_id,
                "consent_hash": consent_key,
                "started_at": now.isoformat(),
                "status": "STARTED",
            }
            conn.execute(
                ops_mail_attempts.insert().values(
                    attempt_id=attempt_id,
                    message_id=message_id,
                    consent_hash=self.consent.digest(),
                    document=json.dumps(attempt),
                )
            )
        # Durable before I/O. Revalidate wall clock/consent immediately before transport.
        if not self.consent.starts_at <= self.clock() < self.consent.expires_at:
            result: Status = "REJECTED"
        else:
            try:
                result = self.sender.send(notice, message_id)
            except Exception:
                result = "UNKNOWN"
        if result not in {"ACCEPTED", "RETRYABLE", "REJECTED", "UNKNOWN"}:
            result = "UNKNOWN"
        with self.journal.transaction() as conn:
            row = conn.execute(
                select(ops_mail).where(ops_mail.c.message_id == message_id).with_for_update()
            ).one()
            doc = json.loads(row.document)
            # Another worker marking an in-flight attempt unknown must not enable a resend.
            if row.status != "SENDING":
                result = "UNKNOWN"
            status: str = "ACKNOWLEDGED" if row.status == "ACKNOWLEDGED" else result
            if result == "RETRYABLE":
                doc["next_at"] = (
                    self.clock() + timedelta(seconds=30 * 2 ** (doc["attempts"] - 1))
                ).isoformat()
                status = "PENDING" if doc["attempts"] < self.consent.max_attempts else "REJECTED"
            if result == "ACCEPTED":
                doc["accepted_at"] = self.clock().isoformat()
                doc["ack_deadline"] = (
                    self.clock() + timedelta(seconds=self.consent.acknowledgement_seconds)
                ).isoformat()
            attempt.update(status=result, finished_at=self.clock().isoformat())
            conn.execute(
                ops_mail_attempts.update()
                .where(ops_mail_attempts.c.attempt_id == attempt_id)
                .values(document=json.dumps(attempt))
            )
            conn.execute(
                ops_mail.update()
                .where(ops_mail.c.message_id == message_id)
                .values(status=status, document=json.dumps(doc))
            )
            record(
                conn,
                row.scope,
                "mail_transport_result",
                {"message_id": message_id, "status": result},
            )
        return status if status == "ACKNOWLEDGED" else result

    def acknowledge(self, message_id: str, owner_reference: Digest) -> None:
        if not re.fullmatch(r"[a-f0-9]{64}", message_id) or not re.fullmatch(
            r"[a-f0-9]{64}", owner_reference
        ):
            raise ValueError("exact message and owner reference hashes required")
        with self.journal.transaction() as conn:
            row = conn.execute(
                select(ops_mail).where(ops_mail.c.message_id == message_id).with_for_update()
            ).one()
            if row.status not in {"ACCEPTED", "UNKNOWN"}:
                raise ValueError("no attempted message to acknowledge")
            doc = json.loads(row.document)
            doc["acknowledged_at"] = self.clock().isoformat()
            conn.execute(
                ops_mail.update()
                .where(ops_mail.c.message_id == message_id)
                .values(status="ACKNOWLEDGED", document=json.dumps(doc))
            )
            record(
                conn,
                row.scope,
                "mail_owner_acknowledged",
                {"message_id": message_id, "owner_reference": owner_reference},
            )

    def resolve_failed(self, message_id: str, owner_reference: Digest) -> None:
        if not re.fullmatch(r"[a-f0-9]{64}", message_id) or not re.fullmatch(
            r"[a-f0-9]{64}", owner_reference
        ):
            raise ValueError("exact message and owner reference hashes required")
        with self.journal.transaction() as conn:
            row = conn.execute(
                select(ops_mail).where(ops_mail.c.message_id == message_id).with_for_update()
            ).one()
            if row.status not in {"UNKNOWN", "REJECTED"}:
                raise ValueError("only failed/ambiguous attempts can be resolved")
            doc = json.loads(row.document)
            doc["resolved_at"] = self.clock().isoformat()
            doc["resolution_reference"] = owner_reference
            conn.execute(
                ops_mail.update()
                .where(ops_mail.c.message_id == message_id)
                .values(document=json.dumps(doc))
            )
            record(
                conn,
                row.scope,
                "mail_failure_reviewed",
                {
                    "message_id": message_id,
                    "owner_reference": owner_reference,
                    "at": doc["resolved_at"],
                },
            )
            # Original outcome/attempts remain. A new acknowledged test must follow resolution.


def delivery_health(
    conn: object, scope: str, now: datetime, *, max_ack_age_seconds: int, run_id: str = "operations"
) -> bool:
    """A verified channel and no failed/overdue notices are required for new risk."""
    from sqlalchemy.engine import Connection

    if not isinstance(conn, Connection):
        raise TypeError("existing readiness transaction required")
    rows = conn.execute(select(ops_mail).where(ops_mail.c.scope == scope).limit(1001)).all()
    if not rows or len(rows) > 1000:
        return False
    latest_ack = None
    latest_resolution = None
    for row in rows:
        doc = json.loads(row.document)
        notice = Notice.model_validate_json(json.dumps(doc["notice"]))
        if notice.run_id != run_id:
            continue
        if row.status in {"UNKNOWN", "REJECTED"}:
            if doc.get("resolved_at") is None:
                return False
            at = datetime.fromisoformat(doc["resolved_at"])
            latest_resolution = max(latest_resolution, at) if latest_resolution else at
        if row.status == "ACKNOWLEDGED" and doc["acknowledged_at"] is not None:
            if (
                0
                <= (now - datetime.fromisoformat(doc["acknowledged_at"])).total_seconds()
                <= max_ack_age_seconds
            ):
                at = datetime.fromisoformat(doc["acknowledged_at"])
                latest_ack = max(latest_ack, at) if latest_ack else at
        elif (
            row.status == "ACCEPTED"
            and doc["ack_deadline"] is not None
            and now >= datetime.fromisoformat(doc["ack_deadline"])
        ):
            return False
    return latest_ack is not None and (latest_resolution is None or latest_ack > latest_resolution)
