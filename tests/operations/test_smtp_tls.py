"""Real disposable loopback TLS SMTP; no external host or owner credential."""

import ipaddress
import smtplib
import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pydantic import SecretStr

from trading_agent.autonomy.fixtures import NOW
from trading_agent.operations.email import EmailProfile, GmailSender, Notice
from trading_agent.supervised.contracts import digest


@pytest.mark.parametrize("drop_reply", [False, True])
def test_disposable_tls_smtp_acceptance_and_ambiguous_data(tmp_path, monkeypatch, drop_reply):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "fixture.crt"
    key_path = tmp_path / "fixture.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5)
    port = listener.getsockname()[1]
    received = []
    errors = []

    def server():
        try:
            raw, _ = listener.accept()
            with server_context.wrap_socket(raw, server_side=True) as conn:
                stream = conn.makefile("rwb", buffering=0)
                stream.write(b"220 localhost fixture SMTP\r\n")
                while line := stream.readline(65536):
                    verb = line.split(b" ", 1)[0].strip().upper()
                    if verb == b"EHLO":
                        stream.write(b"250-localhost\r\n250 AUTH PLAIN\r\n")
                    elif verb in (b"AUTH", b"MAIL", b"RCPT"):
                        stream.write(b"235 ok\r\n" if verb == b"AUTH" else b"250 ok\r\n")
                    elif verb == b"DATA":
                        stream.write(b"354 data\r\n")
                        body = []
                        while (piece := stream.readline(65536)) != b".\r\n":
                            if not piece:
                                raise RuntimeError("truncated fixture message")
                            body.append(piece)
                        received.append(b"".join(body))
                        if drop_reply:
                            return
                        stream.write(b"250 accepted\r\n")
                    elif verb == b"QUIT":
                        stream.write(b"221 bye\r\n")
                        return
                    else:
                        stream.write(b"250 ok\r\n")
        except Exception as error:
            errors.append(type(error).__name__)
        finally:
            listener.close()

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    real_smtp = smtplib.SMTP_SSL
    client_context = ssl.create_default_context(cafile=str(cert_path))
    monkeypatch.setattr(
        "trading_agent.operations.email.ssl.create_default_context", lambda: client_context
    )

    def local_only(host, mail_port, *, timeout, context):
        assert (
            host == "smtp.gmail.com"
            and mail_port == 465
            and context.verify_mode == ssl.CERT_REQUIRED
        )
        return real_smtp("localhost", port, timeout=timeout, context=context)

    monkeypatch.setattr("trading_agent.operations.email.smtplib.SMTP_SSL", local_only)
    profile = EmailProfile(
        enabled=True, sender="owner@example.invalid", recipient="owner@example.invalid"
    )
    sender = GmailSender(profile, lambda: SecretStr("FIXTURE-SMTP-SECRET"))
    notice = Notice(
        domain="OWNER_EMAIL_TEST",
        scope=profile.digest(),
        incident_hash=digest("test"),
        code="OWNER_EMAIL_TEST",
        at=NOW,
    )
    try:
        assert sender.send(notice, digest("message")) == ("UNKNOWN" if drop_reply else "ACCEPTED")
        thread.join(5)
        assert not thread.is_alive() and not errors and len(received) == 1
        assert b"FIXTURE-SMTP-SECRET" not in received[0] and b"OWNER_EMAIL_TEST" in received[0]
    finally:
        listener.close()
