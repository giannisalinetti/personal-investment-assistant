"""On-demand Monitor slice for tickers mentioned but not on the watchlist."""

from __future__ import annotations

import asyncio
import json
import logging

import yfinance as yf

from src.config import DEFAULT_RSI_OVERBOUGHT, DEFAULT_RSI_OVERSOLD, WatchlistEntry
from src.nodes.analyst import compute_technical_signal
from src.nodes.market_data import market_data_node
from src.state import initial_state
from src.tools.yfinance_tool import YFINANCE_CACHE_DIR

logger = logging.getLogger(__name__)

yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))


def _resolve_ticker_name_sync(ticker: str) -> str:
    try:
        fast = yf.Ticker(ticker).fast_info
        for attr in ("short_name", "long_name"):
            value = getattr(fast, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
    except Exception:
        logger.debug("Could not resolve company name for %s", ticker, exc_info=True)
    return ticker


async def build_adhoc_entries(tickers: list[str]) -> list[WatchlistEntry]:
    """Build synthetic watchlist entries with default RSI thresholds."""
    entries: list[WatchlistEntry] = []
    for ticker in tickers:
        name = await asyncio.to_thread(_resolve_ticker_name_sync, ticker)
        entries.append(WatchlistEntry(ticker=ticker, name=name))
    return entries


async def analyze_adhoc_tickers(entries: list[WatchlistEntry]) -> dict | None:
    """Fetch OHLCV, indicators, and technical signals for ad-hoc tickers."""
    if not entries:
        return None

    tickers = [entry.ticker for entry in entries]
    logger.info("Advisor on-demand analysis for: %s", tickers)
    state = initial_state(tickers, run_type="advisor_adhoc")
    market_update = await market_data_node(state, watchlist=entries)
    market_data = market_update.get("market_data", {})
    errors = list(market_update.get("errors", []))

    signals: list[dict] = []
    for ticker, payload in market_data.items():
        signals.append(
            compute_technical_signal(
                ticker,
                bullish=payload.get("bullish", []),
                bearish=payload.get("bearish", []),
            )
        )

    if not market_data and not errors:
        errors.append("No market data returned for requested tickers.")

    return {
        "tickers": tickers,
        "market_data": market_data,
        "signals": signals,
        "errors": errors,
        "rsi_defaults": {
            "oversold": DEFAULT_RSI_OVERSOLD,
            "overbought": DEFAULT_RSI_OVERBOUGHT,
        },
    }


def format_on_demand_block(analysis: dict | None) -> str:
    if not analysis:
        return "No explicit-ticker on-demand analysis for this question."

    payload = {
        "note": (
            "Fetched on demand for tickers mentioned but not in the configured watchlist. "
            "RSI thresholds use defaults (30/70) when not on watchlist.yaml."
        ),
        "tickers": analysis.get("tickers", []),
        "rsi_defaults": analysis.get("rsi_defaults"),
        "signals": analysis.get("signals", []),
        "market_data": analysis.get("market_data", {}),
        "errors": analysis.get("errors", []),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
