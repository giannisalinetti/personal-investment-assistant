"""Telegram notification client."""

from __future__ import annotations

import logging

import httpx
from telegram import Message

from src.config import settings

logger = logging.getLogger(__name__)

# Telegram Bot API hard limit per message.
TELEGRAM_MESSAGE_LIMIT = 4096

_PLACEHOLDER_VALUES = frozenset({"", "your_token_here", "your_chat_id_here"})


def telegram_configured() -> bool:
    token = settings.TELEGRAM_BOT_TOKEN.strip()
    chat_id = settings.TELEGRAM_CHAT_ID.strip()
    if token in _PLACEHOLDER_VALUES or chat_id in _PLACEHOLDER_VALUES:
        return False
    return bool(token and chat_id)


def split_telegram_text(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split text into Telegram-safe chunks, preferring paragraph and line breaks."""
    body = text.strip()
    if not body:
        return [""]
    if len(body) <= limit:
        return [body]

    chunks: list[str] = []
    remaining = body
    min_break = max(limit // 4, 200)

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        window = remaining[:limit]
        split_at = window.rfind("\n\n")
        if split_at < min_break:
            split_at = window.rfind("\n")
        if split_at < min_break:
            split_at = limit

        chunk = remaining[:split_at].rstrip()
        remaining = remaining[split_at:].lstrip()
        if not chunk:
            chunk = remaining[:limit]
            remaining = remaining[len(chunk) :].lstrip()
        chunks.append(chunk)

    if len(chunks) <= 1:
        return chunks

    total = len(chunks)
    return [
        chunk if index == 0 else f"({index + 1}/{total})\n{chunk}"
        for index, chunk in enumerate(chunks)
    ]


async def send_telegram_message(text: str) -> None:
    """Send a message to the configured Telegram chat (splits when over 4096 chars)."""
    if not telegram_configured():
        raise RuntimeError("Telegram is not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")

    chunks = split_telegram_text(text)
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=20.0) as client:
        for chunk in chunks:
            response = await client.post(
                url,
                json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": chunk,
                    "disable_web_page_preview": True,
                },
            )
            response.raise_for_status()
    logger.info(
        "Telegram message sent (%d chars, %d part(s))",
        len(text),
        len(chunks),
    )


async def reply_telegram_text(
    message: Message,
    text: str,
    *,
    disable_web_page_preview: bool = True,
) -> None:
    """Reply in-chat, splitting long Advisor answers across multiple messages."""
    chunks = split_telegram_text(text)
    for chunk in chunks:
        await message.reply_text(
            chunk,
            disable_web_page_preview=disable_web_page_preview,
        )
    if len(chunks) > 1:
        logger.info("Telegram reply split into %d part(s) (%d chars total)", len(chunks), len(text))
