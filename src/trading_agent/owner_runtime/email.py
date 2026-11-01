"""Owner-only Gmail setup/testing. No account/token file or broker privileges.

An eligible owner may store a Gmail app password in macOS Keychain themselves.
The credential is obtained only at SMTP dispatch, never printed or persisted.
The coding agent must not execute these commands against a real owner profile.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL

from ..db.schema import OPS_TABLES, metadata, ops_mail
from ..operations.email import (
    DeliveryConsent,
    Dispatcher,
    EmailProfile,
    GmailSender,
    Notice,
    Status,
    enqueue,
)
from ..operations.monitor import Health, MonitorProfile, monitor_once
from ..security.files import read_private_json, write_private_json
from ..supervised.contracts import digest
from ..supervised.journal import Journal
from .auth import AuthError, owner_root


def keychain_password(profile: EmailProfile) -> SecretStr:
    try:
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                profile.keychain_service,
                "-a",
                profile.sender,
                "-w",
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if result.returncode or not result.stdout.strip() or len(result.stdout) > 4096:
            raise AuthError("owner Gmail credential unavailable")
        return SecretStr(result.stdout.decode().strip())
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        raise AuthError("owner Gmail credential unavailable") from None


def email_command(
    action: str, path: Path, *, message_id: str | None = None, owner_reference: str | None = None
) -> dict[str, Any]:
    root = owner_root(path)
    if action == "worker":
        return worker_once(root)
    profile_path = root / "email-profile.json"
    if action in {"prepare", "prepare-monitor"}:
        # This template is disabled and contains no real identity or credential.
        if not profile_path.exists():
            write_private_json(
                profile_path,
                EmailProfile(
                    sender="owner@example.invalid", recipient="owner@example.invalid"
                ).model_dump(mode="json"),
                replace=False,
            )
        profile = EmailProfile.model_validate_json(json.dumps(read_private_json(profile_path)))
        now = datetime.now(UTC)
        scope = None
        run_id = "operations"
        if action == "prepare-monitor":
            monitor_path = root / "monitor-profile.json"
            if not monitor_path.exists():
                write_private_json(
                    monitor_path,
                    MonitorProfile(scope=digest("UNBOUND_OWNER_MONITOR_SCOPE")).model_dump(
                        mode="json"
                    ),
                    replace=False,
                )
            monitor = MonitorProfile.model_validate_json(
                json.dumps(read_private_json(monitor_path))
            )
            scope, run_id = monitor.scope, monitor.run_id
        proposal = DeliveryConsent(
            profile_hash=profile.digest(),
            purpose="OPERATIONAL_NOTICE" if action == "prepare-monitor" else "OWNER_EMAIL_TEST",
            scope=scope,
            run_id=run_id,
            approved=False,
            starts_at=now,
            expires_at=now + timedelta(hours=1),
            max_messages=100 if action == "prepare-monitor" else 1,
        )
        if not write_private_json(
            root / "email-consent.unsigned.json", proposal.model_dump(mode="json"), replace=False
        ):
            raise AuthError("existing email consent retained; explicit owner review required")
        return {
            "status": "UNSIGNED_DISABLED",
            "review_files": ["email-profile.json", "email-consent.unsigned.json"],
            "authority": "LIVE_NOT_AUTHORIZED",
            "messages_sent": 0,
        }
    profile = EmailProfile.model_validate_json(json.dumps(read_private_json(profile_path)))
    consent = DeliveryConsent.model_validate_json(
        json.dumps(read_private_json(root / "email-consent.json"))
    )
    if consent.purpose != "OWNER_EMAIL_TEST" and action == "test":
        raise AuthError("one-test email consent required")
    if consent.purpose == "FIXTURE":
        raise AuthError("synthetic email consent cannot enable a real sender")
    db = root / "email-journal.sqlite"
    if not db.exists():
        import os

        fd = os.open(db, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    import os
    import stat

    if (
        db.is_symlink()
        or db.stat().st_uid != os.getuid()
        or stat.S_IMODE(db.stat().st_mode) != 0o600
    ):
        raise AuthError("private email journal permissions invalid")
    engine = create_engine(URL.create("sqlite", database=str(db)))
    try:
        metadata.create_all(engine, tables=list(OPS_TABLES))
        now = datetime.now(UTC)
        if action == "status":
            with engine.connect() as conn:
                statuses: list[str] = list(conn.execute(select(ops_mail.c.status)).scalars())
            return {
                "messages": len(statuses),
                "statuses": statuses,
                "authority": "LIVE_NOT_AUTHORIZED",
                "inbox_delivery_attested": False,
            }
        if action in {"ack", "resolve"}:
            if message_id is None or owner_reference is None:
                raise AuthError("exact message and owner reference hashes required")

            class NoSend:
                def send(self, notice: Notice, key: str) -> Status:
                    return "REJECTED"

            dispatcher = Dispatcher(
                engine, NoSend(), profile, consent, clock=lambda: datetime.now(UTC)
            )
            if action == "ack":
                dispatcher.acknowledge(message_id, owner_reference)
            else:
                dispatcher.resolve_failed(message_id, owner_reference)
            return {
                "status": "OWNER_RECORD_SAVED",
                "message_id": message_id,
                "authority": "LIVE_NOT_AUTHORIZED",
                "messages_sent": 0,
            }
        if (
            not profile.enabled
            or not consent.approved
            or consent.profile_hash != profile.digest()
            or not consent.starts_at <= now < consent.expires_at
        ):
            raise AuthError(
                "owner email enablement, exact consent binding and unexpired interval required"
            )
        sender = GmailSender(profile, lambda: keychain_password(profile))
        dispatcher = Dispatcher(engine, sender, profile, consent, clock=lambda: datetime.now(UTC))
        if action == "test":
            # Stable reference prevents a second test message from the same one-message consent.
            notice = Notice(
                domain="OWNER_EMAIL_TEST",
                scope=profile.digest(),
                incident_hash=consent.digest(),
                code="OWNER_EMAIL_TEST",
                at=consent.starts_at,
            )
            with Journal(engine).transaction() as conn:
                message_id = enqueue(conn, notice)
            result = dispatcher.send_one(message_id)
            return {
                "status": result,
                "message_id": message_id,
                "authority": "LIVE_NOT_AUTHORIZED",
                "inbox_delivery_attested": False,
                "note": "SMTP acceptance is not inbox receipt",
            }
        raise AuthError("unsupported email command")
    finally:
        engine.dispose()


def worker_once(path: Path) -> dict[str, Any]:
    """Health checking continues when email consent expires or SMTP is unavailable."""
    root = owner_root(path)
    monitor_profile = MonitorProfile.model_validate_json(
        json.dumps(read_private_json(root / "monitor-profile.json"))
    )
    db = root / "email-journal.sqlite"
    import os
    import stat

    if not db.exists():
        fd = os.open(db, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    if (
        db.is_symlink()
        or db.stat().st_uid != os.getuid()
        or stat.S_IMODE(db.stat().st_mode) != 0o600
    ):
        raise AuthError("private email journal permissions invalid")
    engine = create_engine(URL.create("sqlite", database=str(db)))
    try:
        metadata.create_all(engine, tables=list(OPS_TABLES))
        try:
            health = Health.model_validate_json(
                json.dumps(read_private_json(root / "runtime-health.json"))
            )
        except (OSError, ValueError):
            health = None
        report = monitor_once(engine, monitor_profile, health, now=datetime.now(UTC), fixture=False)
        try:
            profile = EmailProfile.model_validate_json(
                json.dumps(read_private_json(root / "email-profile.json"))
            )
            consent = DeliveryConsent.model_validate_json(
                json.dumps(read_private_json(root / "email-consent.json"))
            )
        except (OSError, ValueError):
            return {
                "monitor": report,
                "delivery": "UNCONFIGURED",
                "authority": "LIVE_NOT_AUTHORIZED",
            }
        if consent.purpose != "OPERATIONAL_NOTICE" or (consent.scope, consent.run_id) != (
            monitor_profile.scope,
            monitor_profile.run_id,
        ):
            return {
                "monitor": report,
                "delivery": "SCOPE_DENIED",
                "authority": "LIVE_NOT_AUTHORIZED",
            }
        dispatcher = Dispatcher(
            engine,
            GmailSender(profile, lambda: keychain_password(profile)),
            profile,
            consent,
            clock=lambda: datetime.now(UTC),
        )
        with engine.connect() as conn:
            pending: list[str] = list(
                conn.execute(
                    select(ops_mail.c.message_id)
                    .where(
                        ops_mail.c.scope == monitor_profile.scope,
                        ops_mail.c.status.in_(["PENDING", "SENDING"]),
                    )
                    .limit(100)
                ).scalars()
            )
        return {
            "monitor": report,
            "delivery_attempt_results": [dispatcher.send_one(key) for key in pending],
            "authority": "LIVE_NOT_AUTHORIZED",
        }
    finally:
        engine.dispose()
