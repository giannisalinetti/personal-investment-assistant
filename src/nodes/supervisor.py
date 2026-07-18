"""Supervisor node — graph entry: watchlist load + market calendar gate."""

from __future__ import annotations

import logging

from src.config import load_watchlist
from src.state import AgentState
from src.tools.market_calendar import log_skipped_run, should_skip_run

logger = logging.getLogger(__name__)


def supervisor_node(state: AgentState) -> dict:
    """Load watchlist and decide whether the pipeline should run.

    Sets ``skipped=True`` when every exchange mapped from the watchlist is
    closed for today (weekends and exchange holidays). LangGraph routes to END
    without running market_data or analyst when skipped.

    Manual runs (dashboard Refresh / ``pia-run --run-type manual``) always
    proceed so operators can refresh last available market data on closed days.
    """
    entries = load_watchlist()
    tickers = [entry.ticker for entry in entries]
    run_type = state.get("run_type", "unknown")

    if run_type == "manual":
        logger.info(
            "Supervisor: run_type=manual watchlist=%s skipped=False (calendar bypass)",
            tickers,
        )
        return {
            "watchlist": tickers,
            "skipped": False,
        }

    skipped, reason, open_by_exchange = should_skip_run(entries)

    logger.info(
        "Supervisor: run_type=%s watchlist=%s skipped=%s open=%s",
        run_type,
        tickers,
        skipped,
        open_by_exchange,
    )

    if skipped:
        log_skipped_run(reason, run_type=run_type)
        return {
            "watchlist": tickers,
            "skipped": True,
        }

    return {
        "watchlist": tickers,
        "skipped": False,
    }
