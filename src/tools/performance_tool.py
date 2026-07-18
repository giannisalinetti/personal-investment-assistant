"""Period return tools for Advisor (close-to-close via yfinance history)."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import yfinance as yf
from langchain_core.tools import tool

from src.config import AssetClass, load_watchlists
from src.tools.yfinance_tool import YFINANCE_CACHE_DIR, yahoo_ticker_candidates

logger = logging.getLogger(__name__)

yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))

ALLOWED_PERIODS = ("1wk", "1mo", "3mo", "ytd", "1y")

# Tool period → yfinance history period(s) to try (first that yields ≥2 closes wins).
_PERIOD_FETCH: dict[str, tuple[str, ...]] = {
    "1wk": ("5d", "1mo"),
    "1mo": ("1mo",),
    "3mo": ("3mo",),
    "ytd": ("ytd",),
    "1y": ("1y",),
}


def _normalize_period(period: str) -> str | None:
    key = period.strip().lower()
    aliases = {
        "1w": "1wk",
        "week": "1wk",
        "1week": "1wk",
        "month": "1mo",
        "1month": "1mo",
        "3month": "3mo",
        "year": "1y",
        "1year": "1y",
    }
    key = aliases.get(key, key)
    return key if key in ALLOWED_PERIODS else None


def _index_as_of(ts: Any) -> str:
    if hasattr(ts, "date"):
        d = ts.date()
        return d.isoformat() if isinstance(d, date) else str(d)
    return str(ts)[:10]


def _fetch_history_closes(ticker: str, yahoo_period: str):
    """Return Close series with ≥2 rows, or None."""
    for candidate in yahoo_ticker_candidates(ticker):
        history = yf.Ticker(candidate).history(period=yahoo_period, interval="1d", auto_adjust=True)
        if history.empty or "Close" not in history.columns:
            continue
        closes = history["Close"].dropna()
        if len(closes) < 2:
            continue
        if candidate.upper() != ticker.strip().upper():
            logger.info(
                "%s: performance using Yahoo symbol %s (%d closes, period=%s)",
                ticker,
                candidate,
                len(closes),
                yahoo_period,
            )
        return closes
    return None


def _fetch_performance_sync(ticker: str, period: str) -> dict:
    """Compute close-to-close return for one ticker over ``period``."""
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
        closes = _fetch_history_closes(symbol, yahoo_period)
        if closes is not None:
            break

    if closes is None:
        return {"ticker": symbol, "period": normalized, "error": "history unavailable"}

    start_price = float(closes.iloc[0])
    end_price = float(closes.iloc[-1])
    if start_price == 0:
        return {"ticker": symbol, "period": normalized, "error": "invalid start price"}

    return_pct = ((end_price - start_price) / start_price) * 100.0
    return {
        "ticker": symbol,
        "period": normalized,
        "return_pct": round(return_pct, 4),
        "start_price": round(start_price, 6),
        "end_price": round(end_price, 6),
        "start_as_of": _index_as_of(closes.index[0]),
        "end_as_of": _index_as_of(closes.index[-1]),
    }


def _watchlist_class_map() -> dict[str, AssetClass]:
    return {entry.ticker.upper(): entry.asset_class for entry in load_watchlists()}


def _resolve_rank_tickers(
    tickers: list[str] | None,
    asset_class: str | None,
) -> tuple[list[str], str | None, str | None]:
    """Return (symbols, normalized_asset_class, error)."""
    class_key: AssetClass | None = None
    if asset_class:
        raw = asset_class.strip().lower()
        if raw not in {"stock", "etf", "etc"}:
            return [], None, f"unsupported asset_class {asset_class!r}; use stock, etf, or etc"
        class_key = raw  # type: ignore[assignment]

    class_map = _watchlist_class_map()
    requested = [t.strip().upper() for t in (tickers or []) if t and str(t).strip()]

    if not requested:
        if class_key is None:
            return [], None, "tickers or asset_class is required"
        symbols = [t for t, cls in class_map.items() if cls == class_key]
        if not symbols:
            return [], class_key, f"no {class_key} tickers on watchlist"
        return symbols, class_key, None

    if class_key is not None:
        filtered = [t for t in requested if class_map.get(t) == class_key]
        # Allow ad-hoc tickers not on watchlist only when no class filter? Plan says drop
        # tickers whose watchlist class ≠ requested. Unknown tickers are dropped.
        dropped = [t for t in requested if t not in filtered]
        if dropped:
            logger.info(
                "rank_performance: dropped out-of-class/unknown tickers for %s: %s",
                class_key,
                ", ".join(dropped),
            )
        if not filtered:
            return [], class_key, f"no tickers remained after {class_key} filter"
        return filtered, class_key, None

    return requested, None, None


def _rank_performance_sync(
    tickers: list[str] | None,
    period: str,
    asset_class: str | None,
) -> dict:
    symbols, class_key, err = _resolve_rank_tickers(tickers, asset_class)
    if err and not symbols:
        payload: dict[str, Any] = {"period": _normalize_period(period) or period, "error": err}
        if class_key:
            payload["asset_class"] = class_key
        return payload

    normalized = _normalize_period(period)
    if normalized is None:
        return {
            "asset_class": class_key,
            "error": f"unsupported period {period!r}; use one of {', '.join(ALLOWED_PERIODS)}",
        }

    ranked: list[dict] = []
    errors: list[dict] = []
    for symbol in symbols:
        row = _fetch_performance_sync(symbol, normalized)
        if "error" in row:
            errors.append({"ticker": symbol, "error": row["error"]})
            continue
        ranked.append(row)

    ranked.sort(key=lambda r: float(r.get("return_pct") or 0), reverse=True)
    return {
        "period": normalized,
        "asset_class": class_key,
        "ranked": ranked,
        "errors": errors,
    }


@tool
def get_performance(ticker: str, period: str = "1wk") -> str:
    """Fetch close-to-close total return for one ticker over a period.

    Periods: 1wk, 1mo, 3mo, ytd, 1y. Use for single-ticker return questions.
    For best/worst across the watchlist, prefer rank_performance instead.
    Do not invent returns — call this tool. Returns JSON text.
    """
    try:
        result = _fetch_performance_sync(ticker, period)
    except Exception as exc:
        logger.warning("%s: get_performance failed: %s", ticker, exc)
        return json.dumps({"ticker": ticker.strip().upper(), "error": str(exc)})
    return json.dumps(result, ensure_ascii=False)


@tool
def rank_performance(
    tickers: list[str] | None = None,
    period: str = "1wk",
    asset_class: str | None = None,
) -> str:
    """Rank tickers by close-to-close return over a period (best first).

    Periods: 1wk, 1mo, 3mo, ytd, 1y. Pass watchlist tickers from context, and/or
    asset_class (stock|etf|etc) to load/filter the watchlist. Prefer this for
    "best performing ETF last week" style questions. Returns JSON text.
    """
    try:
        result = _rank_performance_sync(tickers, period, asset_class)
    except Exception as exc:
        logger.warning("rank_performance failed: %s", exc)
        return json.dumps({"error": str(exc)})
    return json.dumps(result, ensure_ascii=False)
