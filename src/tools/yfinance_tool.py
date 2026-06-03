"""yfinance OHLCV fetcher with retry."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from src.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

MIN_CANDLES = 30
DEFAULT_PERIOD = "6mo"
YFINANCE_CACHE_DIR = PROJECT_ROOT / ".cache" / "yfinance"
YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))


def _fetch_ohlcv_sync(ticker: str, period: str = DEFAULT_PERIOD) -> pd.DataFrame | None:
    """Fetch daily OHLCV for a ticker (blocking)."""
    history = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
    if history.empty:
        return None

    frame = history.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    frame = frame[["open", "high", "low", "close", "volume"]].dropna()
    if len(frame) < MIN_CANDLES:
        return None
    return frame


async def fetch_ohlcv(
    ticker: str,
    *,
    period: str = DEFAULT_PERIOD,
    max_retries: int = 2,
) -> pd.DataFrame | None:
    """Fetch daily OHLCV asynchronously with retries."""
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            frame = await asyncio.to_thread(_fetch_ohlcv_sync, ticker, period)
            if frame is not None:
                return frame
            logger.warning("%s: insufficient OHLCV data (need >= %s candles)", ticker, MIN_CANDLES)
            return None
        except Exception as exc:
            last_error = exc
            logger.warning(
                "%s: fetch attempt %s/%s failed: %s",
                ticker,
                attempt + 1,
                max_retries + 1,
                exc,
            )
            if attempt < max_retries:
                await asyncio.sleep(1)

    if last_error:
        raise last_error
    return None


def latest_close(frame: pd.DataFrame) -> float:
    """Return the most recent closing price."""
    return float(frame["close"].iloc[-1])


def ytd_return_pct(frame: pd.DataFrame) -> float | None:
    """Compute year-to-date return percentage from daily OHLCV."""
    if frame.empty:
        return None
    latest_ts = frame.index[-1]
    year = latest_ts.year if hasattr(latest_ts, "year") else datetime.now().year
    year_frame = frame[frame.index.year == year] if hasattr(frame.index, "year") else frame
    if year_frame.empty:
        return None
    start_close = float(year_frame["close"].iloc[0])
    end_close = float(year_frame["close"].iloc[-1])
    if start_close == 0:
        return None
    return ((end_close - start_close) / start_close) * 100.0


async def validate_ticker(ticker: str) -> bool:
    """Return True if yfinance can resolve the symbol (lightweight check)."""
    try:
        return await asyncio.to_thread(_validate_ticker_sync, ticker)
    except Exception:
        return False


def _validate_ticker_sync(ticker: str) -> bool:
    """Check symbol exists — only needs recent daily data, not 30 candles."""
    history = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=True)
    return not history.empty


def snapshot_market_row(frame: pd.DataFrame, ticker: str) -> dict:
    """Serialize latest OHLCV row for AgentState."""
    latest = frame.iloc[-1]
    index_value = frame.index[-1]
    if isinstance(index_value, datetime):
        as_of = index_value.astimezone(timezone.utc).isoformat()
    else:
        as_of = str(index_value)

    return {
        "ticker": ticker,
        "as_of": as_of,
        "open": float(latest["open"]),
        "high": float(latest["high"]),
        "low": float(latest["low"]),
        "close": float(latest["close"]),
        "volume": float(latest["volume"]),
        "candles": len(frame),
        "ytd_return_pct": ytd_return_pct(frame),
    }
