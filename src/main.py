"""Long-running advisor daemon — Telegram polling for /brief, /ask, /status, /stop."""

from __future__ import annotations

import logging
import sys

from telegram.ext import Application, CommandHandler

from src.bot.telegram_handlers import (
    ask_command,
    brief_command,
    start_command,
    status_command,
    stop_command,
)
from src.config import settings
from src.logging_config import configure_logging
from src.tools.telegram_client import telegram_configured

configure_logging()
logger = logging.getLogger(__name__)


def build_application() -> Application:
    """Build the Telegram application with advisor command handlers."""
    if not telegram_configured():
        raise RuntimeError(
            "Telegram is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env"
        )

    application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("brief", brief_command))
    application.add_handler(CommandHandler("ask", ask_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("stop", stop_command))
    return application


def main() -> None:
    logger.info("Starting PIA advisor daemon (Telegram polling)")
    try:
        application = build_application()
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    application.run_polling(drop_pending_updates=True)
    logger.info("Advisor daemon stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
