"""Serialize Monitor state for the dashboard API and HTML views."""

from __future__ import annotations

from src.config import settings
from src.nodes.notifier import format_suggestion_line
from src.state_persistence import NEXT_RUNS, load_state, stale_state_warning, state_age_hours

SIGNAL_EMOJI = {"BUY": "🟢", "SELL": "🔴", "WATCH": "🟡", "HOLD": "⚪"}


def _format_last_run(document: dict) -> str:
    last_run = document.get("last_run", "unknown")
    run_type = document.get("run_type", "manual")
    if document.get("skipped"):
        return f"{last_run} — skipped ({run_type})"
    return f"{last_run} — {run_type}"


def build_dashboard_view(document: dict | None) -> dict:
    """Build a JSON-serializable dashboard payload."""
    if document is None:
        return {
            "available": False,
            "message": "No state.json found. Run `uv run pia-graph` or wait for a scheduled pia-run.",
            "model": settings.OLLAMA_MODEL,
            "next_runs": NEXT_RUNS,
            "timezone": settings.TIMEZONE,
        }

    age = state_age_hours(document)
    signals = []
    for signal in document.get("signals", []):
        label = signal.get("signal", "HOLD")
        signals.append(
            {
                "ticker": signal.get("ticker", "?"),
                "signal": label,
                "emoji": SIGNAL_EMOJI.get(label, "⚪"),
                "confidence": signal.get("confidence", "—"),
                "rationale": signal.get("rationale", ""),
            }
        )

    suggestions = [
        format_suggestion_line(item).strip()
        for item in document.get("suggestions", [])
    ]

    return {
        "available": True,
        "model": document.get("model", settings.OLLAMA_MODEL),
        "watchlist_count": document.get("watchlist_count"),
        "last_run": _format_last_run(document),
        "run_type": document.get("run_type"),
        "skipped": document.get("skipped"),
        "stale_warning": stale_state_warning(document),
        "state_age_hours": round(age, 2) if age is not None else None,
        "signals": signals,
        "suggestions": suggestions,
        "watchlist_note": document.get("watchlist_note"),
        "errors": document.get("errors", []),
        "next_runs": document.get("next_runs", NEXT_RUNS),
        "timezone": settings.TIMEZONE,
    }


def get_dashboard_view() -> dict:
    return build_dashboard_view(load_state())
