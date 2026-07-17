"""Market data node — fetch OHLCV and compute indicators."""

from __future__ import annotations

import asyncio
import logging

from src.config import WatchlistEntry, load_watchlist
from src.state import AgentState
from src.tools.indicators import compute_indicators, evaluate_indicator_signals
from src.tools.yfinance_tool import fetch_ohlcv, snapshot_market_row

logger = logging.getLogger(__name__)


async def _load_ticker(entry: WatchlistEntry) -> tuple[str, dict | None, str | None]:
    """Fetch and compute indicators for one watchlist entry."""
    ticker = entry.ticker
    try:
        frame = await fetch_ohlcv(ticker)
        if frame is None:
            return ticker, None, f"{ticker}: insufficient OHLCV data"

        enriched = compute_indicators(frame)
        signals = evaluate_indicator_signals(
            enriched,
            rsi_oversold=entry.rsi_oversold,
            rsi_overbought=entry.rsi_overbought,
        )
        payload = {
            "name": entry.name,
            "asset_class": entry.asset_class,
            "snapshot": snapshot_market_row(frame, ticker),
            "indicators": signals.values,
            "bullish": list(signals.bullish),
            "bearish": list(signals.bearish),
        }
        logger.info(
            "%s: close=%.2f bullish=%s bearish=%s",
            ticker,
            payload["snapshot"]["close"],
            signals.bullish,
            signals.bearish,
        )
        return ticker, payload, None
    except Exception as exc:
        message = f"{ticker}: market data failed ({exc})"
        logger.exception(message)
        return ticker, None, message


async def market_data_node(
    state: AgentState,
    *,
    watchlist: list[WatchlistEntry] | None = None,
) -> dict:
    """Fetch market data and indicators for each watchlist ticker."""
    entries = watchlist or load_watchlist()
    new_errors: list[str] = []
    market_data: dict[str, dict] = {}

    results = await asyncio.gather(*[_load_ticker(entry) for entry in entries])
    for ticker, payload, error in results:
        if error:
            new_errors.append(error)
        if payload is not None:
            market_data[ticker] = payload

    return {"market_data": market_data, "errors": new_errors}
