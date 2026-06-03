"""Extract likely stock ticker symbols from free-form Advisor questions."""

from __future__ import annotations

import re

from src.config import WatchlistEntry

_DOLLAR_TICKER = re.compile(r"\$([A-Za-z]{1,5}(?:\.[A-Za-z]{1,2})?)\b")
_CAPS_TICKER = re.compile(r"\b([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\b")

# All-caps tokens that are not ticker symbols.
_STOPWORDS = frozenset(
    {
        "A",
        "AI",
        "ALL",
        "AM",
        "AN",
        "AND",
        "ARE",
        "AS",
        "ASK",
        "AT",
        "BE",
        "BOY",
        "BUY",
        "BY",
        "CAN",
        "CEO",
        "DAY",
        "DID",
        "DO",
        "EMA",
        "ETF",
        "EU",
        "EUR",
        "FED",
        "FOR",
        "FYI",
        "GDP",
        "GET",
        "HAS",
        "HE",
        "HER",
        "HIM",
        "HIS",
        "HOLD",
        "HOW",
        "I",
        "IF",
        "IN",
        "IPO",
        "IS",
        "IT",
        "ITS",
        "LET",
        "MACD",
        "MAY",
        "ME",
        "MY",
        "NEW",
        "NOT",
        "NOW",
        "OF",
        "OLD",
        "ON",
        "ONE",
        "OR",
        "OUR",
        "OUT",
        "PM",
        "PUT",
        "RSI",
        "SAY",
        "SEC",
        "SELL",
        "SHE",
        "SO",
        "THE",
        "TO",
        "TOO",
        "UK",
        "UP",
        "US",
        "USD",
        "USE",
        "VS",
        "WAS",
        "WATCH",
        "WE",
        "WHO",
        "WHY",
        "YTD",
        "YOU",
    }
)


def _watchlist_symbols(watchlist: list[WatchlistEntry]) -> set[str]:
    symbols: set[str] = set()
    for entry in watchlist:
        ticker = entry.ticker.upper()
        symbols.add(ticker)
        symbols.add(ticker.split(".")[0])
    return symbols


def _is_adhoc_candidate(symbol: str, watchlist_symbols: set[str]) -> bool:
    upper = symbol.upper()
    base = upper.split(".")[0]
    if base in _STOPWORDS or upper in _STOPWORDS:
        return False
    if upper in watchlist_symbols or base in watchlist_symbols:
        return False
    return True


def extract_adhoc_tickers(text: str, watchlist: list[WatchlistEntry]) -> list[str]:
    """Return uppercase tickers mentioned in text that are not on the watchlist."""
    if not text.strip():
        return []

    watchlist_symbols = _watchlist_symbols(watchlist)
    seen: set[str] = set()
    candidates: list[str] = []

    for match in _DOLLAR_TICKER.finditer(text):
        symbol = match.group(1).upper()
        if not _is_adhoc_candidate(symbol, watchlist_symbols) or symbol in seen:
            continue
        seen.add(symbol)
        candidates.append(symbol)

    for match in _CAPS_TICKER.finditer(text):
        symbol = match.group(1).upper()
        if not _is_adhoc_candidate(symbol, watchlist_symbols) or symbol in seen:
            continue
        seen.add(symbol)
        candidates.append(symbol)

    return candidates
