from datetime import UTC, datetime, timedelta

import pytest

from trading_agent.operations.email import DeliveryConsent, EmailProfile
from trading_agent.operations.monitor import MonitorProfile
from trading_agent.owner_runtime.auth import AuthError
from trading_agent.owner_runtime.email import email_command
from trading_agent.security.files import read_private_json, write_private_json
from trading_agent.supervised.contracts import digest


def test_private_prepare_is_disabled_and_test_cannot_read_keychain(tmp_path, monkeypatch):
    monkeypatch.setattr("trading_agent.owner_runtime.email.owner_root", lambda path: tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("real email/credential operation")

    monkeypatch.setattr("trading_agent.owner_runtime.email.keychain_password", forbidden)
    monkeypatch.setattr("smtplib.SMTP_SSL", forbidden)
    assert email_command("prepare", tmp_path)["status"] == "UNSIGNED_DISABLED"
    consent = read_private_json(tmp_path / "email-consent.unsigned.json")
    assert consent["approved"] is False
    write_private_json(tmp_path / "email-consent.json", consent, replace=False)
    with pytest.raises(AuthError):
        email_command("test", tmp_path)
    with pytest.raises(AuthError):
        email_command("prepare", tmp_path)


def test_independent_monitor_continues_with_expired_email_consent(tmp_path, monkeypatch):
    monkeypatch.setattr("trading_agent.owner_runtime.email.owner_root", lambda path: tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("external SMTP/keychain attempted")

    monkeypatch.setattr("trading_agent.owner_runtime.email.keychain_password", forbidden)
    monkeypatch.setattr("smtplib.SMTP_SSL", forbidden)
    cfg = MonitorProfile(enabled=True, scope=digest("private fixture scope"))
    profile = EmailProfile(
        enabled=False, sender="owner@example.invalid", recipient="owner@example.invalid"
    )
    now = datetime.now(UTC)
    consent = DeliveryConsent(
        profile_hash=profile.digest(),
        scope=cfg.scope,
        purpose="OPERATIONAL_NOTICE",
        approved=True,
        starts_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    for name, obj in (
        ("monitor-profile.json", cfg),
        ("email-profile.json", profile),
        ("email-consent.json", consent),
    ):
        write_private_json(tmp_path / name, obj.model_dump(mode="json"), replace=False)
    result = email_command("worker", tmp_path)
    assert result["monitor"]["status"] == "ALERT"
    assert result["delivery_attempt_results"] == ["DENIED"]
    again = email_command("worker", tmp_path)
    assert again["monitor"]["message_id"] is None
