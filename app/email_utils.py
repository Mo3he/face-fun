"""SMTP helper for emailing captured photos to a user-supplied address."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from .config import Settings


class EmailError(Exception):
    pass


def _build_client(settings: Settings) -> smtplib.SMTP:
    host = settings.get("smtp_host")
    port = int(settings.get("smtp_port", 587))
    if not host:
        raise EmailError("SMTP is not configured. Ask an administrator to set it up.")
    use_tls = bool(settings.get("smtp_use_tls", True))

    if port == 465:
        client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
    else:
        client = smtplib.SMTP(host, port, timeout=20)
        if use_tls:
            client.starttls(context=ssl.create_default_context())

    user = settings.get("smtp_user")
    password = settings.get("smtp_password")
    if user and password:
        client.login(user, password)
    return client


def send_photos(settings: Settings, recipient: str, photo_paths: list[Path]) -> None:
    sender = settings.get("smtp_from") or settings.get("smtp_user")
    if not sender:
        raise EmailError("No sender address configured for outgoing email.")

    message = EmailMessage()
    message["Subject"] = "Your Face Fun photos"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "Hi,\n\nAttached are the photos you captured with Face Fun.\n\nEnjoy!"
    )

    for path in photo_paths:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        message.add_attachment(data, maintype="image", subtype="jpeg", filename=path.name)

    try:
        client = _build_client(settings)
        with client:
            client.send_message(message)
    except EmailError:
        raise
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailError(f"Failed to send email: {exc}") from exc


def send_test(settings: Settings, recipient: str) -> None:
    sender = settings.get("smtp_from") or settings.get("smtp_user")
    if not sender:
        raise EmailError("No sender address configured for outgoing email.")
    message = EmailMessage()
    message["Subject"] = "Face Fun SMTP test"
    message["From"] = sender
    message["To"] = recipient
    message.set_content("This is a test email from Face Fun. SMTP is working.")
    try:
        client = _build_client(settings)
        with client:
            client.send_message(message)
    except EmailError:
        raise
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailError(f"Failed to send test email: {exc}") from exc
