"""Market data node — fetch OHLCV and compute indicators."""

from __future__ import annotations

import logging

from src.config import WatchlistEntry, load_watchlist
from src.state import AgentState
from src.tools.indicators import compute_indicators, evaluate_indicator_signals
from src.tools.yfinance_tool import fetch_ohlcv, snapshot_market_row

logger = logging.getLogger(__name__)


async def market_data_node(
    state: AgentState,
    *,
    watchlist: list[WatchlistEntry] | None = None,
) -> dict:
    """Fetch market data and indicators for each watchlist ticker."""
    entries = watchlist or load_watchlist()
    new_errors: list[str] = []
    market_data: dict[str, dict] = {}

    for entry in entries:
        ticker = entry.ticker
        try:
            frame = await fetch_ohlcv(ticker)
            if frame is None:
                new_errors.append(f"{ticker}: insufficient OHLCV data")
                continue

            enriched = compute_indicators(frame)
            signals = evaluate_indicator_signals(
                enriched,
                rsi_oversold=entry.rsi_oversold,
                rsi_overbought=entry.rsi_overbought,
            )
            market_data[ticker] = {
                "name": entry.name,
                "snapshot": snapshot_market_row(frame, ticker),
                "indicators": signals.values,
                "bullish": list(signals.bullish),
                "bearish": list(signals.bearish),
            }
            logger.info(
                "%s: close=%.2f bullish=%s bearish=%s",
                ticker,
                market_data[ticker]["snapshot"]["close"],
                signals.bullish,
                signals.bearish,
            )
        except Exception as exc:
            message = f"{ticker}: market data failed ({exc})"
            logger.exception(message)
            new_errors.append(message)

    return {"market_data": market_data, "errors": new_errors}
