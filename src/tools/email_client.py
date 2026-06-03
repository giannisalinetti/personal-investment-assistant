"""Email notification client (SMTP)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from src.config import settings

logger = logging.getLogger(__name__)

_PLACEHOLDER_VALUES = frozenset({"", "your@email.com", "your_app_password"})


def email_configured() -> bool:
    if not settings.EMAIL_ENABLED:
        return False
    address = settings.EMAIL_ADDRESS.strip()
    password = settings.EMAIL_PASSWORD.strip()
    recipient = settings.EMAIL_RECIPIENT.strip()
    if address in _PLACEHOLDER_VALUES or password in _PLACEHOLDER_VALUES:
        return False
    return bool(address and password and recipient)


def _build_subject(run_type: str) -> str:
    tz = ZoneInfo(settings.TIMEZONE)
    today = datetime.now(tz).strftime("%Y-%m-%d")
    return f"[PIA] Market Update — {today} ({run_type})"


def _send_email_sync(subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.EMAIL_ADDRESS
    message["To"] = settings.EMAIL_RECIPIENT
    message.set_content(body)

    with smtplib.SMTP(settings.EMAIL_SMTP_HOST, settings.EMAIL_SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(settings.EMAIL_ADDRESS, settings.EMAIL_PASSWORD)
        server.send_message(message)


async def send_email(subject: str, body: str) -> None:
    """Send a plain-text email via configured SMTP."""
    if not email_configured():
        raise RuntimeError("Email is not configured (EMAIL_ENABLED and credentials required)")
    await asyncio.to_thread(_send_email_sync, subject, body)
    logger.info("Email sent to %s (%d chars)", settings.EMAIL_RECIPIENT, len(body))


async def send_market_update_email(body: str, *, run_type: str) -> None:
    """Send a market update with the standard PIA subject line."""
    await send_email(_build_subject(run_type), body)
