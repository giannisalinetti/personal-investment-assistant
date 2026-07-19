"""yfinance OHLCV fetcher with retry and Yahoo symbol resolution."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from src.config import PROJECT_ROOT
from src.tools.risk_metrics import compute_risk_metrics

logger = logging.getLogger(__name__)

MIN_CANDLES = 30
DEFAULT_PERIOD = "6mo"
YFINANCE_CACHE_DIR = PROJECT_ROOT / ".cache" / "yfinance"
YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))

# Symbols Yahoo cannot feed with enough daily history (indexes, wrong venues).
# Map to a liquid, same-theme instrument when possible.
YAHOO_TICKER_ALIASES: dict[str, str] = {
    # FTSE All-World *index* on gettex — not a tradeable ETF (sparse/no history)
    "AW01.FGI": "VWCE.DE",
}

# When a bare European UCITS ticker has no data, try common Yahoo suffixes.
_EURO_SUFFIXES = (".DE", ".L", ".AS")


def resolve_yahoo_ticker(ticker: str) -> str:
    """Return the preferred Yahoo symbol (alias applied)."""
    key = ticker.strip().upper()
    return YAHOO_TICKER_ALIASES.get(key, ticker.strip())


def yahoo_ticker_candidates(ticker: str) -> list[str]:
    """Ordered Yahoo symbols to try for OHLCV fetch."""
    primary = resolve_yahoo_ticker(ticker)
    candidates: list[str] = []
    seen: set[str] = set()

    def add(symbol: str) -> None:
        key = symbol.upper()
        if key in seen:
            return
        seen.add(key)
        candidates.append(symbol)

    add(primary)
    # If caller still has the raw watchlist ticker and it differs from alias
    add(ticker.strip())

    bare = primary.split(".", 1)[0]
    # Futures / FX already have venue markers (=F, =X)
    if "=" not in primary and "." not in primary:
        for suffix in _EURO_SUFFIXES:
            add(f"{bare}{suffix}")

    return candidates


def _fetch_ohlcv_sync(ticker: str, period: str = DEFAULT_PERIOD) -> pd.DataFrame | None:
    """Fetch daily OHLCV for a ticker (blocking), trying Yahoo aliases/suffixes."""
    best_count = 0
    for candidate in yahoo_ticker_candidates(ticker):
        history = yf.Ticker(candidate).history(period=period, interval="1d", auto_adjust=True)
        if history.empty:
            continue
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
        best_count = max(best_count, len(frame))
        if len(frame) < MIN_CANDLES:
            continue
        if candidate.upper() != ticker.strip().upper():
            logger.info(
                "%s: using Yahoo symbol %s (%d candles)",
                ticker,
                candidate,
                len(frame),
            )
        return frame

    if best_count:
        logger.warning(
            "%s: insufficient OHLCV data (best candidate had %s candles, need >= %s)",
            ticker,
            best_count,
            MIN_CANDLES,
        )
    else:
        logger.warning("%s: insufficient OHLCV data (need >= %s candles)", ticker, MIN_CANDLES)
    return None


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
            return await asyncio.to_thread(_fetch_ohlcv_sync, ticker, period)
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
    """Check symbol exists — try aliases; only needs recent daily data, not 30 candles."""
    for candidate in yahoo_ticker_candidates(ticker):
        history = yf.Ticker(candidate).history(period="5d", interval="1d", auto_adjust=True)
        if not history.empty:
            return True
    return False


def snapshot_market_row(frame: pd.DataFrame, ticker: str) -> dict:
    """Serialize latest OHLCV row for AgentState."""
    latest = frame.iloc[-1]
    index_value = frame.index[-1]
    if isinstance(index_value, datetime):
        as_of = index_value.astimezone(timezone.utc).isoformat()
    else:
        as_of = str(index_value)

    risk = compute_risk_metrics(
        frame["close"],
        window=DEFAULT_PERIOD,
        benchmark=None,
    )

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
        "std_dev_ann_pct": risk.get("std_dev_ann_pct"),
        "max_drawdown_pct": risk.get("max_drawdown_pct"),
        "risk_window": DEFAULT_PERIOD,
    }
