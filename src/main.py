"""Long-running advisor daemon — Telegram polling for /brief, /ask, /status, /stop."""

from __future__ import annotations

import logging
import sys

from telegram.ext import Application, CommandHandler, ContextTypes

from src.bot.telegram_handlers import (
    ask_command,
    brief_command,
    clear_command,
    start_command,
    status_command,
    stop_command,
)
from src.cli import command_parser
from src.config import settings
from src.logging_config import configure_logging
from src.monitor_scheduler import start_monitor_scheduler, stop_monitor_scheduler
from src.tools.telegram_client import telegram_configured

configure_logging()
logger = logging.getLogger(__name__)


def build_application() -> Application:
    """Build the Telegram application with advisor command handlers."""
    if not telegram_configured():
        raise RuntimeError(
            "Telegram is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env"
        )

    application = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .get_updates_connect_timeout(60.0)
        .get_updates_read_timeout(90.0)
        .get_updates_write_timeout(30.0)
        .get_updates_pool_timeout(30.0)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("brief", brief_command))
    application.add_handler(CommandHandler("ask", ask_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_error_handler(_log_telegram_error)
    return application


async def _post_init(application: Application) -> None:
    start_monitor_scheduler()
    logger.info(
        "pia-bot ready (Monitor scheduler %s)",
        "on" if settings.PIA_MONITOR_SCHEDULER else "off",
    )


async def _post_shutdown(application: Application) -> None:
    stop_monitor_scheduler()


async def _log_telegram_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log handler failures (common after sleep when the network stack recovers slowly)."""
    if context.error is not None:
        logger.exception(
            "Telegram handler error (update=%s): %s",
            update,
            context.error,
        )


def _parse_args() -> None:
    parser = command_parser(
        "pia-bot",
        "Long-running Advisor daemon — Telegram polling for /brief, /ask, and related commands.",
        epilog=(
            "Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.\n"
            "With PIA_MONITOR_SCHEDULER=true (default), also runs Monitor at 08:00/13:00/17:30.\n"
            "Set PIA_MONITOR_SCHEDULER=false when using K8s CronJobs or Compose Ofelia.\n\n"
            "Telegram commands: /start  /brief  /ask  /clear  /status  /stop\n\n"
            "Examples:\n"
            "  uv run pia-bot\n"
            "  ./docker/up.sh   # home stack: pia-web + pia-bot (see docs/compose.md)"
        ),
    )
    parser.parse_args()


def main() -> None:
    _parse_args()
    logger.info("Starting PIA advisor daemon (Telegram polling)")
    try:
        application = build_application()
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    # drop_pending_updates avoids a burst of stale commands after wake from sleep
    application.run_polling(
        drop_pending_updates=True,
        bootstrap_retries=-1,
        close_loop=False,
    )
    logger.info("Advisor daemon stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
