"""Telegram bot command handlers for Advisor mode."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from src.config import load_watchlist, settings
from src.nodes.advisor import advisor_respond
from src.state_persistence import NEXT_RUNS, load_state, stale_state_warning
from src.tools.telegram_client import telegram_configured

logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
_CONVERSATION_KEY = "advisor_history"


def _authorized(update: Update) -> bool:
    if update.effective_chat is None:
        return False
    expected = settings.TELEGRAM_CHAT_ID.strip()
    if not expected:
        return False
    return str(update.effective_chat.id) == expected


def _history(context: ContextTypes.DEFAULT_TYPE) -> list[dict]:
    if _CONVERSATION_KEY not in context.application.bot_data:
        context.application.bot_data[_CONVERSATION_KEY] = []
    return context.application.bot_data[_CONVERSATION_KEY]


def _truncate(text: str, limit: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> str:
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
    await update.message.reply_text("🧠 Thinking… this may take a few minutes.")
    watchlist = load_watchlist()
    state = load_state()
    history = _history(context)
    answer = await advisor_respond(
        question=question,
        state=state,
        watchlist=watchlist,
        history=history,
        mode=mode,
    )
    if mode == "ask" and question:
        history.append({"role": "user", "content": question})
    elif mode == "brief":
        history.append({"role": "user", "content": "/brief"})
    history.append({"role": "assistant", "content": answer})
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
        "Personal Investment Assistant advisor is running.\n"
        "Commands: /brief  /ask <question>  /status  /stop"
    )
