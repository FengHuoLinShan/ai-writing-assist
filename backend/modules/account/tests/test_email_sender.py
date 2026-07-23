from __future__ import annotations

from core.config import Settings
from modules.account import email_sender


class _FakeSmtpClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def ehlo(self) -> None:
        self.calls.append("ehlo")

    def starttls(self, *, context) -> None:
        assert context is not None
        self.calls.append("starttls")

    def login(self, username: str, password: str) -> None:
        assert username == "sender"
        assert password == "secret"
        self.calls.append("login")

    def send_message(self, message) -> None:
        assert message["To"] == "reader@example.com"
        self.calls.append("send")


def _settings(mode: str) -> Settings:
    return Settings(
        smtp_host="smtp.example.com",
        smtp_port=465 if mode == "ssl" else 587,
        smtp_tls_mode=mode,
        smtp_username="sender",
        smtp_password="secret",
        smtp_from="sender@example.com",
    )


def test_sender_rejects_unknown_tls_mode_before_opening_socket(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        email_sender.smtplib,
        "SMTP",
        lambda *_args, **_kwargs: opened.append("smtp"),
    )
    monkeypatch.setattr(
        email_sender.smtplib,
        "SMTP_SSL",
        lambda *_args, **_kwargs: opened.append("smtp_ssl"),
    )

    try:
        email_sender._send_message_sync(
            _settings("plaintext"),
            "reader@example.com",
            "123456",
        )
    except RuntimeError as exc:
        assert "SMTP_TLS_MODE" in str(exc)
    else:
        raise AssertionError("unknown SMTP TLS mode was accepted")

    assert opened == []


def test_sender_uses_starttls_for_starttls_mode(monkeypatch) -> None:
    client = _FakeSmtpClient()
    monkeypatch.setattr(
        email_sender.smtplib,
        "SMTP_SSL",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("SMTP_SSL must not be used for starttls")
        ),
    )
    monkeypatch.setattr(
        email_sender.smtplib,
        "SMTP",
        lambda *_args, **_kwargs: client,
    )

    email_sender._send_message_sync(
        _settings("starttls"),
        "reader@example.com",
        "123456",
    )

    assert client.calls == ["ehlo", "starttls", "ehlo", "login", "send"]


def test_sender_uses_implicit_tls_for_ssl_mode(monkeypatch) -> None:
    client = _FakeSmtpClient()
    monkeypatch.setattr(
        email_sender.smtplib,
        "SMTP",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("SMTP must not be used for ssl")
        ),
    )
    monkeypatch.setattr(
        email_sender.smtplib,
        "SMTP_SSL",
        lambda *_args, **_kwargs: client,
    )

    email_sender._send_message_sync(
        _settings("ssl"),
        "reader@example.com",
        "123456",
    )

    assert client.calls == ["login", "send"]
