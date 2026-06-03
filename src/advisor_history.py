"""Persisted Advisor conversation history (atomic JSON)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from src.config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)

ADVISOR_DATA_DIR = PROJECT_ROOT / "data" / "advisor"
HISTORY_PATH = ADVISOR_DATA_DIR / "history.json"
HISTORY_TMP_PATH = ADVISOR_DATA_DIR / "history.json.tmp"


def _empty_document(*, telegram_chat_id: str | None = None) -> dict:
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "telegram_chat_id": telegram_chat_id or settings.TELEGRAM_CHAT_ID or None,
        "turns": [],
    }


def load_history_document() -> dict:
    """Load the full history document, or return an empty schema."""
    if not HISTORY_PATH.exists():
        return _empty_document()
    try:
        document = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read advisor history: %s", exc)
        return _empty_document()
    if not isinstance(document, dict):
        return _empty_document()
    if not isinstance(document.get("turns"), list):
        document["turns"] = []
    return document


def load_turns() -> list[dict]:
    """Return conversation turns capped for Advisor prompts."""
    turns = load_history_document().get("turns", [])
    if not isinstance(turns, list):
        return []
    max_turns = settings.ADVISOR_HISTORY_MAX_TURNS
    cleaned: list[dict] = []
    for turn in turns[-max_turns:]:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        content = turn.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            cleaned.append({"role": role, "content": content})
    return cleaned


def save_turns(turns: list[dict], *, telegram_chat_id: str | None = None) -> Path:
    """Persist turns atomically."""
    ADVISOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
    max_turns = settings.ADVISOR_HISTORY_MAX_TURNS
    trimmed = turns[-max_turns:]
    document = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "telegram_chat_id": telegram_chat_id or settings.TELEGRAM_CHAT_ID or None,
        "turns": trimmed,
    }
    payload = json.dumps(document, indent=2, ensure_ascii=False)
    payload = f"{payload}\n"
    HISTORY_TMP_PATH.write_text(payload, encoding="utf-8")
    os.replace(HISTORY_TMP_PATH, HISTORY_PATH)
    logger.info("Persisted %d advisor turns to %s", len(trimmed), HISTORY_PATH)
    return HISTORY_PATH


def append_exchange(
    *,
    user: str,
    assistant: str,
    telegram_chat_id: str | None = None,
) -> list[dict]:
    """Append one user/assistant exchange and persist."""
    turns = load_turns()
    turns.append({"role": "user", "content": user})
    turns.append({"role": "assistant", "content": assistant})
    save_turns(turns, telegram_chat_id=telegram_chat_id)
    return turns


def clear_history(*, telegram_chat_id: str | None = None) -> None:
    """Reset persisted conversation history."""
    save_turns([], telegram_chat_id=telegram_chat_id)
    logger.info("Advisor conversation history cleared")
