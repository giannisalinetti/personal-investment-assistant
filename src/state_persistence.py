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
