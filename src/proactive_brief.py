"""Send proactive daily brief after pre-market Monitor runs."""

from __future__ import annotations

import logging

from src.config import load_watchlist, settings
from src.nodes.advisor import advisor_respond
from src.state import AgentState
from src.tools.email_client import email_configured, send_market_update_email
from src.tools.telegram_client import send_telegram_message, telegram_configured

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4096


def _should_send_proactive_brief(state: AgentState) -> bool:
    if not settings.PROACTIVE_BRIEF_ENABLED:
        return False
    if state.get("run_type") != "pre_market":
        return False
    if state.get("skipped"):
        return False
    if settings.PROACTIVE_BRIEF_SKIP_IF_NOTIFY and state.get("notification_sent"):
        logger.info("Proactive brief skipped — Monitor notification already sent")
        return False
    via = settings.proactive_brief_channels
    if not via:
        return False
    can_send = False
    if "telegram" in via and telegram_configured():
        can_send = True
    if "email" in via and email_configured():
        can_send = True
    return can_send


def _truncate(text: str, limit: int = TELEGRAM_MAX_LENGTH) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n\n… [truncated]"


async def maybe_send_proactive_brief(state: AgentState) -> None:
    """Generate and dispatch a daily brief when configured for pre-market runs."""
    if not _should_send_proactive_brief(state):
        return

    watchlist = load_watchlist()
    logger.info("Generating proactive pre-market brief")
    try:
        brief = await advisor_respond(
            question="",
            state=dict(state),
            watchlist=watchlist,
            history=[],
            mode="brief",
        )
    except Exception:
        logger.exception("Proactive brief generation failed")
        return

    header = "📋 Proactive daily brief — pre_market\n\n"
    message = _truncate(f"{header}{brief}")
    via = settings.proactive_brief_channels
    errors: list[str] = []

    if "telegram" in via and telegram_configured():
        try:
            await send_telegram_message(message)
            logger.info("Proactive brief sent via Telegram")
        except Exception as exc:
            logger.exception("Proactive brief Telegram dispatch failed: %s", exc)
            errors.append(str(exc))

    if "email" in via and email_configured():
        try:
            await send_market_update_email(message, run_type="pre_market_brief")
            logger.info("Proactive brief sent via email")
        except Exception as exc:
            logger.exception("Proactive brief email dispatch failed: %s", exc)
            errors.append(str(exc))

    if errors:
        logger.warning("Proactive brief dispatch errors: %s", "; ".join(errors))
