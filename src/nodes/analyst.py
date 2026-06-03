"""Analyst node — rule-based signals, LLM rationale polish, and watchlist note."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from statistics import mean

from src.config import settings
from src.llm import get_llm
from src.state import AgentState

logger = logging.getLogger(__name__)

CONFIDENCE_HIGH = 0.75
CONFIDENCE_MEDIUM = 0.55
SIGNAL_THRESHOLD = 0.5
JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def compute_technical_signal(
    ticker: str,
    *,
    bullish: list[str],
    bearish: list[str],
    news_sentiment: float | None = None,
) -> dict:
    """Compute BUY/SELL/HOLD/WATCH from indicator confirmations."""
    bullish_count = len(bullish)
    bearish_count = len(bearish)
    confirming_count = max(bullish_count, bearish_count)
    technical_score = min(1.0, confirming_count * 0.25)

    if news_sentiment is None:
        normalized_news = 0.5
    else:
        normalized_news = (news_sentiment + 1) / 2

    strength = (technical_score * 0.7) + (normalized_news * 0.3)

    if bullish_count >= 2 and strength >= SIGNAL_THRESHOLD:
        signal = "BUY"
    elif bearish_count >= 2 and strength >= SIGNAL_THRESHOLD:
        signal = "SELL"
    elif bullish_count + bearish_count == 1:
        signal = "WATCH"
    else:
        signal = "HOLD"

    if strength >= CONFIDENCE_HIGH:
        confidence = "HIGH"
    elif strength >= CONFIDENCE_MEDIUM:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    if bullish and bearish:
        rationale = f"Bullish: {', '.join(bullish)}; Bearish: {', '.join(bearish)}"
    elif bullish:
        rationale = "; ".join(bullish)
    elif bearish:
        rationale = "; ".join(bearish)
    else:
        rationale = "No confirming signals"

    if news_sentiment is not None:
        rationale = f"{rationale}; News sentiment: {news_sentiment:+.1f}"

    return {
        "ticker": ticker,
        "signal": signal,
        "strength": round(strength, 3),
        "rationale": rationale,
        "confidence": confidence,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
    }


def _average_sentiment(news_items: list[dict], ticker: str) -> float | None:
    scores = [item["sentiment"] for item in news_items if item.get("ticker") == ticker]
    if not scores:
        return None
    return float(mean(scores))


def _build_watchlist_note(market_data: dict) -> str | None:
    """Compare YTD performance among monitored tickers (no holdings)."""
    returns: list[tuple[str, float]] = []
    for ticker, payload in market_data.items():
        ytd = payload.get("snapshot", {}).get("ytd_return_pct")
        if ytd is not None:
            returns.append((ticker, float(ytd)))

    if len(returns) < 2:
        return None

    returns.sort(key=lambda item: item[1], reverse=True)
    best_ticker, best_ytd = returns[0]
    second_ticker, second_ytd = returns[1]
    spread = best_ytd - second_ytd
    return (
        f"Among your watchlist, {best_ticker} leads YTD at {best_ytd:+.1f}% "
        f"({spread:.1f}% ahead of {second_ticker} at {second_ytd:+.1f}%)."
    )


def _polish_language_sync(
    signals: list[dict],
    watchlist_note: str | None,
) -> tuple[dict[str, str], str | None]:
    """Rewrite rationales and optional watchlist note for notifications (one LLM call)."""
    if not signals and not watchlist_note:
        return {}, watchlist_note

    lines = []
    for signal in signals:
        lines.append(
            f"- {signal['ticker']} ({signal['signal']}, {signal['confidence']}): {signal['rationale']}"
        )

    prompt_parts = [
        "Rewrite the following investment signal notes for a concise notification.",
        "Keep factual content — do not change BUY/SELL/HOLD/WATCH meaning.",
        "Use short, readable phrases (e.g. 'RSI oversold (28), MACD bullish cross, neutral news').",
        "Return ONLY JSON with keys:",
        '  "rationales": {"TICKER": "polished text", ...}',
        '  "watchlist_note": "polished one-liner or null"',
        "",
        "Signals:",
        *lines,
    ]
    if watchlist_note:
        prompt_parts.extend(["", f"Watchlist note draft: {watchlist_note}"])
    else:
        prompt_parts.extend(["", "Watchlist note draft: null"])

    llm = get_llm(temperature=0.2)
    response = llm.invoke("\n".join(prompt_parts))
    content = str(response.content if hasattr(response, "content") else response)
    match = JSON_OBJECT_PATTERN.search(content)
    if not match:
        return {}, watchlist_note

    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return {}, watchlist_note

    rationales_raw = parsed.get("rationales", {})
    rationales: dict[str, str] = {}
    if isinstance(rationales_raw, dict):
        for ticker, text in rationales_raw.items():
            if isinstance(text, str) and text.strip():
                rationales[str(ticker).upper()] = text.strip()

    polished_note = watchlist_note
    note_value = parsed.get("watchlist_note")
    if isinstance(note_value, str) and note_value.strip():
        polished_note = note_value.strip()

    return rationales, polished_note


async def analyst_node(state: AgentState) -> dict:
    """Build per-ticker signals from market_data and news_items."""
    market_data = state.get("market_data", {})
    news_items = state.get("news_items", [])
    signals: list[dict] = []

    for ticker, payload in market_data.items():
        signal = compute_technical_signal(
            ticker,
            bullish=payload.get("bullish", []),
            bearish=payload.get("bearish", []),
            news_sentiment=_average_sentiment(news_items, ticker),
        )
        signals.append(signal)

    watchlist_note = _build_watchlist_note(market_data)
    new_errors: list[str] = []

    try:
        polished_rationales, polished_note = await asyncio.to_thread(
            _polish_language_sync,
            signals,
            watchlist_note,
        )
        for signal in signals:
            polished = polished_rationales.get(signal["ticker"].upper())
            if polished:
                signal["rationale"] = polished
        if polished_note:
            watchlist_note = polished_note
    except Exception as exc:
        message = f"Analyst LLM rationale polish failed ({exc})"
        logger.warning(message)
        new_errors.append(message)

    logger.info("Analyst: %d signals, watchlist_note=%s", len(signals), bool(watchlist_note))
    result: dict = {"signals": signals, "watchlist_note": watchlist_note}
    if new_errors:
        result["errors"] = new_errors
    return result
