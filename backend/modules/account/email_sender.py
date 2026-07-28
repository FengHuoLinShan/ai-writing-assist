"""Small bounded SMTP sender for browser login codes."""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.headerregistry import Address
from email.message import EmailMessage

from core.config import Settings, get_settings

_send_slots = asyncio.Semaphore(4)
_SENDER_DISPLAY_NAME = "NovalCraft"


def _send_message_sync(settings: Settings, recipient: str, code: str) -> None:
    if settings.smtp_tls_mode not in {"starttls", "ssl"}:
        raise RuntimeError("SMTP_TLS_MODE must be starttls or ssl")
    message = EmailMessage()
    message["Subject"] = "你的登录验证码"
    message["From"] = Address(
        display_name=_SENDER_DISPLAY_NAME,
        addr_spec=settings.smtp_from,
    )
    message["To"] = recipient
    message.set_content(
        f"验证码：{code}。\n\n"
        "有效期：5 分钟。\n"
        "请勿转发。如果不是你本人操作，可以忽略此邮件。"
    )
    context = ssl.create_default_context()
    if settings.smtp_tls_mode == "ssl":
        client_context = smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
            context=context,
        )
    else:
        client_context = smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        )
    with client_context as client:
        if settings.smtp_tls_mode == "starttls":
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)


async def send_login_code(
    recipient: str,
    code: str,
    *,
    settings: Settings | None = None,
) -> None:
    """Send one code without copying SMTP credentials into logs or task payloads."""
    resolved = settings or get_settings()
    async with _send_slots:
        await asyncio.to_thread(_send_message_sync, resolved, recipient, code)
