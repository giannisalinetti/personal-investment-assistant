"""Telegram bot command handlers for Advisor mode."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from src.advisor_history import append_exchange, clear_history, load_turns
from src.config import load_watchlist, settings
from src.advisor_scan import scan_status_message
from src.nodes.advisor import advisor_respond, resolve_advisor_targets
from src.nodes.notifier import DISCLAIMER
from src.state_persistence import NEXT_RUNS, load_state, stale_state_warning
from src.tools.telegram_client import telegram_configured

logger = logging.getLogger(__name__)

_TELEGRAM_MAX_MESSAGE_LENGTH = 4096
_DISCLAIMER_SHOWN_KEY = "disclaimer_shown"


def _authorized(update: Update) -> bool:
    if update.effective_chat is None:
        return False
    expected = settings.TELEGRAM_CHAT_ID.strip()
    if not expected:
        return False
    return str(update.effective_chat.id) == expected


def _history(context: ContextTypes.DEFAULT_TYPE) -> list[dict]:
    return load_turns()


def _chat_id(update: Update) -> str | None:
    if update.effective_chat is None:
        return None
    return str(update.effective_chat.id)


def _truncate(text: str, limit: int = _TELEGRAM_MAX_MESSAGE_LENGTH) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n\n… [truncated]"


async def _reply_advisor(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    question: str,
    mode: str,
) -> None:
    if update.message is None:
        return
    watchlist = load_watchlist()
    targets, on_demand, scan = await resolve_advisor_targets(
        question=question,
        watchlist=watchlist,
        mode=mode,
    )
    if scan_message := scan_status_message(scan):
        status = f"📊 {scan_message.capitalize()}…"
    elif on_demand and on_demand.get("tickers"):
        tickers = ", ".join(on_demand["tickers"])
        status = f"📊 On-demand analysis for {tickers}…"
    elif targets:
        status = f"🧠 Fetching headlines for {', '.join(e.ticker for e in targets)}…"
    else:
        status = "🧠 Thinking… this may take a few minutes."
    await update.message.reply_text(status)
    state = load_state()
    history = _history(context)
    answer = await advisor_respond(
        question=question,
        state=state,
        watchlist=watchlist,
        history=history,
        mode=mode,
        resolved=(targets, on_demand, scan),
    )
    user_label = question if mode == "ask" and question else "/brief"
    append_exchange(
        user=user_label,
        assistant=answer,
        telegram_chat_id=_chat_id(update),
    )
    await update.message.reply_text(_truncate(answer), disable_web_page_preview=True)


async def brief_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await _reply_advisor(update, context, question="", mode="brief")


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    question = " ".join(context.args or []).strip()
    if not question:
        await update.message.reply_text("Usage: /ask <your question>")
        return
    await _reply_advisor(update, context, question=question, mode="ask")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    if update.message is None:
        return

    state = load_state()
    next_runs = "\n".join(f"  • {name}: {time}" for name, time in NEXT_RUNS.items())
    if state is None:
        last_run_line = "No Monitor run yet"
        signals_line = "Signals: —"
    else:
        last_run_line = f"{state.get('last_run', 'unknown')} ({state.get('run_type', 'manual')})"
        signals_line = f"Signals: {len(state.get('signals', []))}"
        warning = stale_state_warning(state)
        if warning:
            last_run_line = f"{last_run_line}\n⚠️ {warning}"

    msg = (
        "🤖 Personal Investment Assistant — Advisor daemon\n\n"
        f"⏱ Next Monitor runs ({settings.TIMEZONE}):\n{next_runs}\n\n"
        f"🧠 Model: {settings.OLLAMA_MODEL}\n"
        f"📋 Watchlist: {len(load_watchlist())} tickers\n"
        f"🕐 Last Monitor run: {last_run_line}\n"
        f"{signals_line}"
    )
    await update.message.reply_text(msg)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    if update.message is None:
        return
    clear_history(telegram_chat_id=_chat_id(update))
    await update.message.reply_text("Conversation history cleared.")


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    if update.message is None:
        return
    await update.message.reply_text("🛑 Shutting down Personal Investment Assistant advisor daemon…")
    logger.info("Stop requested via Telegram")
    context.application.stop_running()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    if update.message is None:
        return
    if not telegram_configured():
        await update.message.reply_text("Telegram is not fully configured in .env")
        return
    await update.message.reply_text(
        f"{DISCLAIMER}\n\n"
        "Personal Investment Assistant advisor is running.\n"
        "Commands: /brief  /ask <question>  /clear  /status  /stop"
    )
    context.application.bot_data[_DISCLAIMER_SHOWN_KEY] = True
