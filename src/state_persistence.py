"""Atomic persistence of graph output to data/state.json."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from src.config import PROJECT_ROOT, WatchlistEntry, load_watchlist, settings, watchlist_counts
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

_MAX_HEADLINES_PER_TICKER = 5


def _lean_indicators(raw: object) -> dict[str, float | None]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float | None] = {}
    for key in ("rsi_14", "macd", "macd_signal", "ema_20", "ema_50", "bb_lower", "close"):
        value = raw.get(key)
        if value is None:
            out[key] = None
        else:
            try:
                out[key] = float(value)
            except (TypeError, ValueError):
                out[key] = None
    return out


def _build_ticker_details(state: AgentState, watchlist: list[WatchlistEntry]) -> dict[str, dict]:
    """Compact per-ticker snapshot for dashboard expand panels."""
    names = {entry.ticker.upper(): entry.name for entry in watchlist}
    market_data = state.get("market_data") or {}
    news_items = state.get("news_items") or []

    details: dict[str, dict] = {}
    for ticker, payload in market_data.items():
        key = str(ticker).upper()
        snapshot = payload.get("snapshot") if isinstance(payload, dict) else {}
        if not isinstance(snapshot, dict):
            snapshot = {}
        details[key] = {
            "name": payload.get("name") or names.get(key, key),
            "asset_class": payload.get("asset_class", "stock"),
            "close": snapshot.get("close"),
            "as_of": snapshot.get("as_of"),
            "ytd_return_pct": snapshot.get("ytd_return_pct"),
            "bullish": list(payload.get("bullish") or []),
            "bearish": list(payload.get("bearish") or []),
            "indicators": _lean_indicators(payload.get("indicators")),
            "headlines": [],
        }

    for item in news_items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("ticker", "")).upper()
        if not key:
            continue
        if key not in details:
            details[key] = {
                "name": names.get(key, key),
                "asset_class": "stock",
                "close": None,
                "as_of": None,
                "ytd_return_pct": None,
                "bullish": [],
                "bearish": [],
                "indicators": {},
                "headlines": [],
            }
        headlines = details[key]["headlines"]
        if len(headlines) >= _MAX_HEADLINES_PER_TICKER:
            continue
        headlines.append(
            {
                "headline": item.get("headline") or "",
                "source": item.get("source") or "",
                "link": item.get("link") or "",
                "sentiment": item.get("sentiment"),
            }
        )

    # Ensure watchlist names exist even when market_data failed for a ticker
    for entry in watchlist:
        key = entry.ticker.upper()
        if key not in details:
            details[key] = {
                "name": entry.name,
                "asset_class": entry.asset_class,
                "close": None,
                "as_of": None,
                "ytd_return_pct": None,
                "bullish": [],
                "bearish": [],
                "indicators": {},
                "headlines": [],
            }
        elif not details[key].get("name"):
            details[key]["name"] = entry.name

    return details


def state_to_document(state: AgentState) -> dict:
    """Build the JSON document written for the console and scheduled runs."""
    entries = load_watchlist()
    counts = watchlist_counts(entries)
    return {
        "last_run": state.get("run_timestamp") or datetime.now(timezone.utc).isoformat(),
        "run_type": state.get("run_type", "manual"),
        "skipped": bool(state.get("skipped")),
        "next_runs": NEXT_RUNS,
        "model": settings.OLLAMA_MODEL,
        "watchlist_count": len(entries),
        "watchlist_counts": counts,
        "signals": state.get("signals", []),
        "suggestions": state.get("suggestions", []),
        "watchlist_note": state.get("watchlist_note"),
        "notification_sent": bool(state.get("notification_sent")),
        "errors": state.get("errors", []),
        "ticker_details": _build_ticker_details(state, entries),
    }


_PRESERVE_ON_SKIP = (
    "signals",
    "suggestions",
    "watchlist_note",
    "ticker_details",
    "errors",
    "notification_sent",
)


def persist_state(state: AgentState) -> Path:
    """Write state atomically so readers never see a partial file.

    When the run is skipped (markets closed), keep the previous analysis fields
    so a weekend/holiday skip does not wipe the last successful Monitor output.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    document = state_to_document(state)

    if document.get("skipped"):
        previous = load_state()
        if previous and not previous.get("skipped"):
            for key in _PRESERVE_ON_SKIP:
                if key in previous:
                    document[key] = previous[key]
            logger.info(
                "Skipped run — preserved prior signals/suggestions from last successful state"
            )

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
            "No Monitor run data found. Click Refresh Monitor on the dashboard, "
            "or wait for the next scheduled run (08:00 / 13:00 / 17:30)."
        )
    age = state_age_hours(document)
    if age is None:
        return "Monitor state timestamp is invalid — results may be unreliable."
    if age > settings.ADVISOR_STALE_STATE_HOURS:
        return (
            f"Monitor data is {age:.1f}h old (stale after "
            f"{settings.ADVISOR_STALE_STATE_HOURS:g}h). Click Refresh Monitor "
            "on the dashboard, or wait for the next scheduled run "
            f"({', '.join(f'{k} {v}' for k, v in NEXT_RUNS.items())} {settings.TIMEZONE})."
        )
    return None
