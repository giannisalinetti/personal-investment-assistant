"""Telegram notification client."""

from __future__ import annotations

import logging

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

_PLACEHOLDER_VALUES = frozenset({"", "your_token_here", "your_chat_id_here"})


def telegram_configured() -> bool:
    token = settings.TELEGRAM_BOT_TOKEN.strip()
    chat_id = settings.TELEGRAM_CHAT_ID.strip()
    if token in _PLACEHOLDER_VALUES or chat_id in _PLACEHOLDER_VALUES:
        return False
    return bool(token and chat_id)


async def send_telegram_message(text: str) -> None:
    """Send a message to the configured Telegram chat."""
    if not telegram_configured():
        raise RuntimeError("Telegram is not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            url,
            json={
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            },
        )
        response.raise_for_status()
    logger.info("Telegram message sent (%d chars)", len(text))
