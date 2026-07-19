"""Advisor tool: volatility / beta / max drawdown from yfinance history."""

from __future__ import annotations

import json
import logging
from typing import Any

import yfinance as yf
from langchain_core.tools import tool

from src.config import load_watchlists
from src.tools.risk_metrics import compute_risk_metrics
from src.tools.yfinance_tool import YFINANCE_CACHE_DIR, yahoo_ticker_candidates

logger = logging.getLogger(__name__)

yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))

ALLOWED_PERIODS = ("6mo", "1y")
_PERIOD_FETCH: dict[str, tuple[str, ...]] = {
    "6mo": ("6mo",),
    "1y": ("1y",),
}
_EURO_SUFFIXES = (".DE", ".L", ".AS")


def _normalize_period(period: str) -> str | None:
    key = period.strip().lower()
    aliases = {
        "6m": "6mo",
        "6month": "6mo",
        "year": "1y",
        "1year": "1y",
        "12mo": "1y",
    }
    key = aliases.get(key, key)
    return key if key in ALLOWED_PERIODS else None


def _fetch_closes(ticker: str, yahoo_period: str):
    """Daily Close series with ≥5 rows (enough for crude risk stats)."""
    for candidate in yahoo_ticker_candidates(ticker):
        history = yf.Ticker(candidate).history(period=yahoo_period, interval="1d", auto_adjust=True)
        if history.empty or "Close" not in history.columns:
            continue
        closes = history["Close"].dropna()
        if len(closes) < 5:
            continue
        if candidate.upper() != ticker.strip().upper():
            logger.info(
                "%s: risk using Yahoo symbol %s (%d closes, period=%s)",
                ticker,
                candidate,
                len(closes),
                yahoo_period,
            )
        return closes
    return None


def resolve_benchmark(ticker: str, explicit: str | None = None) -> str:
    """Pick beta benchmark: explicit, else VWCE.DE for EU listings if on watchlist, else SPY."""
    if explicit and explicit.strip():
        return explicit.strip().upper()

    symbol = ticker.strip().upper()
    is_euro = any(symbol.endswith(suffix) for suffix in _EURO_SUFFIXES)
    if is_euro:
        watchlist_tickers = {e.ticker.upper() for e in load_watchlists()}
        if "VWCE.DE" in watchlist_tickers:
            return "VWCE.DE"
    return "SPY"


def _fetch_risk_sync(
    ticker: str,
    period: str = "1y",
    benchmark: str | None = None,
) -> dict[str, Any]:
    symbol = ticker.strip().upper()
    if not symbol:
        return {"error": "ticker is required"}

    normalized = _normalize_period(period)
    if normalized is None:
        return {
            "ticker": symbol,
            "error": f"unsupported period {period!r}; use one of {', '.join(ALLOWED_PERIODS)}",
        }

    closes = None
    for yahoo_period in _PERIOD_FETCH[normalized]:
        closes = _fetch_closes(symbol, yahoo_period)
        if closes is not None:
            break
    if closes is None:
        return {"ticker": symbol, "period": normalized, "error": "history unavailable"}

    bench_symbol = resolve_benchmark(symbol, benchmark)
    bench_closes = None
    for yahoo_period in _PERIOD_FETCH[normalized]:
        bench_closes = _fetch_closes(bench_symbol, yahoo_period)
        if bench_closes is not None:
            break

    metrics = compute_risk_metrics(
        closes,
        benchmark_closes=bench_closes,
        window=normalized,
        benchmark=bench_symbol if bench_closes is not None else None,
    )
    if bench_closes is None:
        metrics["beta_error"] = f"benchmark history unavailable for {bench_symbol}"

    return {
        "ticker": symbol,
        "period": normalized,
        **metrics,
    }


@tool
def get_risk(
    ticker: str,
    period: str = "1y",
    benchmark: str | None = None,
) -> str:
    """Fetch volatility risk metrics for one ticker from daily price history.

    Periods: 6mo, 1y. Returns annualized std_dev_ann_pct, max_drawdown_pct (negative %),
    and beta vs a benchmark (default SPY; European .DE/.L/.AS tickers use VWCE.DE when
    that ETF is on the watchlist). Prefer this for ETF volatility / drawdown / beta
    questions. Do not invent risk numbers. Returns JSON text.
    """
    try:
        result = _fetch_risk_sync(ticker, period, benchmark)
    except Exception as exc:
        logger.warning("%s: get_risk failed: %s", ticker, exc)
        return json.dumps({"ticker": ticker.strip().upper(), "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)
