"""Notifier node — format and dispatch market update messages."""

from __future__ import annotations

import logging

from src.config import ASSET_CLASS_LABELS, settings
from src.state import AgentState
from src.tools.email_client import email_configured, send_market_update_email
from src.tools.telegram_client import send_telegram_message, telegram_configured

logger = logging.getLogger(__name__)

DISCLAIMER = "⚠️ Not financial advice. Always do your own research."

_CLASS_ORDER = ("stock", "etf", "etc")


def format_suggestion_line(item: dict) -> str:
    """Format a discovery suggestion with ticker, full name, and reason."""
    ticker = item["ticker"]
    name = str(item.get("name", "")).strip()
    reason = str(item.get("reason", "")).strip()
    asset_class = item.get("asset_class")
    class_tag = f" [{asset_class}]" if asset_class else ""
    label = f"{ticker} — {name}" if name and name.upper() != ticker else ticker
    if reason:
        short = reason if len(reason) <= 100 else f"{reason[:97]}…"
        return f"  {label}{class_tag} — {short}"
    return f"  {label}{class_tag}"


def _is_notifiable_signal(signal: dict) -> bool:
    if signal["signal"] in {"BUY", "SELL"}:
        return signal["confidence"] != "LOW" or not settings.SKIP_LOW_CONFIDENCE
    if signal["signal"] == "WATCH":
        return signal["confidence"] in {"MEDIUM", "HIGH"}
    return False


def should_notify(state: AgentState) -> bool:
    """Return True when the spec says a notification should be sent."""
    if state.get("skipped"):
        return False

    notifiable = [signal for signal in state.get("signals", []) if _is_notifiable_signal(signal)]
    if notifiable:
        return True
    if state.get("suggestions"):
        return True
    if state.get("watchlist_note"):
        return True
    return False


def _short_rationale(text: str, limit: int = 120) -> str:
    body = " ".join(str(text).split())
    if len(body) <= limit:
        return body
    return f"{body[: limit - 1]}…"


def _confidence_short(confidence: str) -> str:
    return {"HIGH": "HI", "MEDIUM": "MED", "LOW": "LO"}.get(confidence, confidence)


def format_notification(state: AgentState) -> str:
    """Build a compact notification body, grouped by asset class."""
    run_type = state.get("run_type", "manual")
    lines = [f"Market Update — {run_type}"]

    notifiable = [signal for signal in state.get("signals", []) if _is_notifiable_signal(signal)]
    shown = 0
    for asset_class in _CLASS_ORDER:
        class_signals = [
            signal
            for signal in notifiable
            if signal.get("asset_class", "stock") == asset_class
        ]
        if not class_signals:
            continue
        lines.append(ASSET_CLASS_LABELS.get(asset_class, asset_class))
        for signal in class_signals:
            if shown >= settings.MAX_TICKERS_PER_NOTIFICATION:
                break
            emoji = {"BUY": "🟢", "SELL": "🔴", "WATCH": "🟡"}.get(signal["signal"], "⚪")
            conf = _confidence_short(str(signal.get("confidence", "")))
            rationale = _short_rationale(signal.get("rationale", ""))
            line = f"{emoji} {signal['ticker']} {signal['signal']} {conf}"
            if rationale:
                line = f"{line} — {rationale}"
            lines.append(line)
            shown += 1
        if shown >= settings.MAX_TICKERS_PER_NOTIFICATION:
            break

    if len(notifiable) > settings.MAX_TICKERS_PER_NOTIFICATION:
        lines.append(
            f"… +{len(notifiable) - settings.MAX_TICKERS_PER_NOTIFICATION} more"
        )

    watchlist_note = state.get("watchlist_note")
    if watchlist_note:
        lines.append(f"Note: {_short_rationale(watchlist_note, 160)}")

    suggestions = state.get("suggestions", [])
    if suggestions:
        lines.append("Related:")
        for item in suggestions:
            lines.append(format_suggestion_line(item).strip())

    lines.append(DISCLAIMER)
    return "\n".join(lines)


async def notifier_node(state: AgentState) -> dict:
    """Dispatch notification via Telegram and/or email when configured."""
    if not should_notify(state):
        logger.info("Notifier: nothing to send")
        return {"notification_sent": False}

    message = format_notification(state)
    run_type = state.get("run_type", "manual")
    dispatch_errors: list[str] = []
    sent_any = False

    if telegram_configured():
        try:
            await send_telegram_message(message)
            sent_any = True
        except Exception as exc:
            logger.exception("Telegram dispatch failed: %s", exc)
            dispatch_errors.append(f"Telegram dispatch failed ({exc})")
    else:
        logger.debug("Notifier: Telegram not configured")

    if email_configured():
        try:
            await send_market_update_email(message, run_type=run_type)
            sent_any = True
        except Exception as exc:
            logger.exception("Email dispatch failed: %s", exc)
            dispatch_errors.append(f"Email dispatch failed ({exc})")

    if not telegram_configured() and not email_configured():
        logger.debug("Notifier: console preview handled by run_graph (%d chars)", len(message))
        sent_any = True

    result: dict = {"notification_sent": sent_any}
    if dispatch_errors:
        result["errors"] = dispatch_errors
    return result
