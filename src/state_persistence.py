"""Atomic persistence of graph output to data/state.json."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from src.config import PROJECT_ROOT, settings
from src.state import AgentState

logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"
STATE_PATH = DATA_DIR / "state.json"
STATE_TMP_PATH = DATA_DIR / "state.json.tmp"

NEXT_RUNS = {
    "pre_market": "08:00",
    "midday": "13:00",
    "end_of_day": "17:30",
}


def state_to_document(state: AgentState) -> dict:
    """Build the JSON document written for the console and scheduled runs."""
    watchlist = state.get("watchlist", [])
    return {
        "last_run": state.get("run_timestamp") or datetime.now(timezone.utc).isoformat(),
        "run_type": state.get("run_type", "manual"),
        "skipped": bool(state.get("skipped")),
        "next_runs": NEXT_RUNS,
        "model": settings.OLLAMA_MODEL,
        "watchlist_count": len(watchlist),
        "signals": state.get("signals", []),
        "suggestions": state.get("suggestions", []),
        "watchlist_note": state.get("watchlist_note"),
        "notification_sent": bool(state.get("notification_sent")),
        "errors": state.get("errors", []),
    }


def persist_state(state: AgentState) -> Path:
    """Write state atomically so readers never see a partial file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    document = state_to_document(state)
    payload = json.dumps(document, indent=2, ensure_ascii=False)
    payload = f"{payload}\n"

    STATE_TMP_PATH.write_text(payload, encoding="utf-8")
    os.replace(STATE_TMP_PATH, STATE_PATH)
    logger.info("Persisted state to %s", STATE_PATH)
    return STATE_PATH


def load_state() -> dict | None:
    """Load persisted Monitor state, or None if missing or invalid."""
    if not STATE_PATH.exists():
        return None
    try:
        document = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read state.json: %s", exc)
        return None
    return document if isinstance(document, dict) else None


def state_age_hours(document: dict) -> float | None:
    """Return hours since last_run, or None if timestamp is missing or invalid."""
    last_run = document.get("last_run")
    if not last_run:
        return None
    try:
        parsed = datetime.fromisoformat(str(last_run).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    return delta.total_seconds() / 3600.0


def is_state_stale(document: dict | None) -> bool:
    """Return True when state is missing or older than ADVISOR_STALE_STATE_HOURS."""
    if document is None:
        return True
    age = state_age_hours(document)
    if age is None:
        return True
    return age > settings.ADVISOR_STALE_STATE_HOURS


def stale_state_warning(document: dict | None) -> str | None:
    """Return a user-facing warning when Monitor state is missing or stale."""
    if document is None:
        return (
            "No Monitor run data found. Run `uv run pia-graph` or wait for the next "
            "scheduled `pia-run` before asking for analysis."
        )
    age = state_age_hours(document)
    if age is None:
        return "Monitor state timestamp is invalid — results may be unreliable."
    if age > settings.ADVISOR_STALE_STATE_HOURS:
        return (
            f"Monitor data is {age:.1f}h old (stale after "
            f"{settings.ADVISOR_STALE_STATE_HOURS:g}h). Consider running "
            "`uv run pia-graph` for fresh signals."
        )
    return None
