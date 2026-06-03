"""Central logging setup — file by default, optional console for debugging."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from src.config import PROJECT_ROOT, settings

APP_LOG = PROJECT_ROOT / "logs" / "app.log"
NOISY_LOGGERS = ("httpx", "httpcore", "yfinance", "peewee")


def configure_logging() -> None:
    """Route application logs to logs/app.log; keep CLI stdout for Rich output only."""
    APP_LOG.parent.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    file_handler = RotatingFileHandler(
        APP_LOG,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if settings.LOG_TO_CONSOLE:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
