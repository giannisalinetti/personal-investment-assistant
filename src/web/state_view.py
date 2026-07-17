"""Serialize Monitor state for the dashboard API and HTML views."""

from __future__ import annotations

from src.config import ASSET_CLASS_LABELS, load_watchlist, settings, watchlist_counts
from src.nodes.notifier import format_suggestion_line
from src.state_persistence import NEXT_RUNS, load_state, stale_state_warning, state_age_hours

SIGNAL_EMOJI = {"BUY": "🟢", "SELL": "🔴", "WATCH": "🟡", "HOLD": "⚪"}
_CLASS_ORDER = ("stock", "etf", "etc")
_RATIONALE_PREVIEW = 96


def _format_last_run(document: dict) -> str:
    last_run = document.get("last_run", "unknown")
    run_type = document.get("run_type", "manual")
    if document.get("skipped"):
        return f"{last_run} — skipped ({run_type})"
    return f"{last_run} — {run_type}"


def _preview(text: str, limit: int = _RATIONALE_PREVIEW) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _signal_row(signal: dict, details: dict[str, dict], names: dict[str, str]) -> dict:
    label = signal.get("signal", "HOLD")
    ticker = str(signal.get("ticker", "?")).upper()
    detail = details.get(ticker) or {}
    name = detail.get("name") or names.get(ticker) or ticker
    rationale = signal.get("rationale", "") or ""
    return {
        "ticker": ticker,
        "name": name,
        "asset_class": signal.get("asset_class") or detail.get("asset_class") or "stock",
        "signal": label,
        "emoji": SIGNAL_EMOJI.get(label, "⚪"),
        "confidence": signal.get("confidence", "—"),
        "rationale": rationale,
        "rationale_preview": _preview(rationale),
        "detail": {
            "close": detail.get("close"),
            "as_of": detail.get("as_of"),
            "ytd_return_pct": detail.get("ytd_return_pct"),
            "bullish": detail.get("bullish") or [],
            "bearish": detail.get("bearish") or [],
            "indicators": detail.get("indicators") or {},
            "headlines": detail.get("headlines") or [],
        },
    }


def build_dashboard_view(document: dict | None) -> dict:
    """Build a JSON-serializable dashboard payload with per-class sections."""
    if document is None:
        return {
            "available": False,
            "message": "No state.json found. Run `uv run pia-graph` or wait for a scheduled pia-run.",
            "model": settings.OLLAMA_MODEL,
            "next_runs": NEXT_RUNS,
            "timezone": settings.TIMEZONE,
            "sections": [],
            "watchlist_counts": watchlist_counts(),
        }

    age = state_age_hours(document)
    entries = load_watchlist()
    names = {entry.ticker.upper(): entry.name for entry in entries}
    details_raw = document.get("ticker_details") or {}
    details = {str(key).upper(): value for key, value in details_raw.items() if isinstance(value, dict)}

    all_signals = [_signal_row(signal, details, names) for signal in document.get("signals", [])]
    counts = document.get("watchlist_counts") or watchlist_counts()

    sections = []
    for asset_class in _CLASS_ORDER:
        class_signals = [s for s in all_signals if s["asset_class"] == asset_class]
        sections.append(
            {
                "asset_class": asset_class,
                "label": ASSET_CLASS_LABELS.get(asset_class, asset_class),
                "watchlist_count": counts.get(asset_class, 0),
                "signals": class_signals,
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
        "watchlist_counts": counts,
        "last_run": _format_last_run(document),
        "run_type": document.get("run_type"),
        "skipped": document.get("skipped"),
        "stale_warning": stale_state_warning(document),
        "state_age_hours": round(age, 2) if age is not None else None,
        "signals": all_signals,
        "sections": sections,
        "suggestions": suggestions,
        "watchlist_note": document.get("watchlist_note"),
        "errors": document.get("errors", []),
        "next_runs": document.get("next_runs", NEXT_RUNS),
        "timezone": settings.TIMEZONE,
    }


def get_dashboard_view() -> dict:
    return build_dashboard_view(load_state())
