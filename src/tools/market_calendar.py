"""Market calendar helpers — exchange mapping and skip logic."""

from __future__ import annotations

import logging
from datetime import date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

from src.config import PROJECT_ROOT, WatchlistEntry, settings

logger = logging.getLogger(__name__)

SCHEDULER_LOG = PROJECT_ROOT / "logs" / "scheduler.log"

# v1 exchange map (see SPEC.md — Market calendar)
EXCHANGE_BY_SUFFIX = {
    ".DE": "XETR",
}
DEFAULT_US_EXCHANGE = "NYSE"


def exchange_for_ticker(ticker: str) -> str:
    """Map a watchlist ticker symbol to a pandas_market_calendars exchange code."""
    upper = ticker.upper()
    for suffix, exchange in EXCHANGE_BY_SUFFIX.items():
        if upper.endswith(suffix):
            return exchange
    return DEFAULT_US_EXCHANGE


@lru_cache(maxsize=8)
def _get_calendar(exchange: str):
    return mcal.get_calendar(exchange)


def is_exchange_open(exchange: str, day: date) -> bool:
    """Return True if the exchange has a trading session on ``day``."""
    calendar = _get_calendar(exchange)
    schedule = calendar.schedule(start_date=day.isoformat(), end_date=day.isoformat())
    return not schedule.empty


def exchanges_for_watchlist(entries: list[WatchlistEntry]) -> dict[str, str]:
    """Return ticker → exchange mapping for a watchlist."""
    return {entry.ticker: exchange_for_ticker(entry.ticker) for entry in entries}


def should_skip_run(
    entries: list[WatchlistEntry],
    *,
    day: date | None = None,
) -> tuple[bool, str, dict[str, bool]]:
    """Return whether to skip the run and a human-readable reason.

    Skip when **every** exchange relevant to the watchlist is closed.
    """
    day = day or _today_in_settings_tz()
    mapping = exchanges_for_watchlist(entries)
    unique_exchanges = sorted(set(mapping.values()))

    open_by_exchange = {exchange: is_exchange_open(exchange, day) for exchange in unique_exchanges}
    if any(open_by_exchange.values()):
        open_names = [name for name, is_open in open_by_exchange.items() if is_open]
        logger.info(
            "Market calendar: %s — open exchanges: %s",
            day.isoformat(),
            ", ".join(open_names),
        )
        return False, "", open_by_exchange

    reason = (
        f"Skipped run on {day.isoformat()}: all watchlist exchanges closed "
        f"({', '.join(unique_exchanges)})"
    )
    logger.info(reason)
    return True, reason, open_by_exchange


def log_skipped_run(reason: str, *, run_type: str) -> None:
    """Append a skipped-run entry to ``logs/scheduler.log``."""
    SCHEDULER_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(ZoneInfo(settings.TIMEZONE)).isoformat()
    line = f"{timestamp} run_type={run_type} {reason}\n"
    with SCHEDULER_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _today_in_settings_tz() -> date:
    return datetime.now(ZoneInfo(settings.TIMEZONE)).date()
