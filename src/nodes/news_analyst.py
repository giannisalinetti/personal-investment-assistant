"""News analyst node — RSS fetch + batched LLM sentiment scoring."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from src.config import load_watchlist, settings
from src.llm import get_llm
from src.state import AgentState
from src.tools.news_fetcher import (
    fetch_all_feeds,
    filter_relevant_articles,
    watchlist_google_news_feed,
)

logger = logging.getLogger(__name__)

SENTIMENT_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
JSON_ARRAY_PATTERN = re.compile(r"\[.*\]", re.DOTALL)


def _clamp_sentiment(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _parse_sentiment_batch(response_text: str, count: int) -> list[float]:
    """Parse a JSON array of sentiment scores; pad or trim to ``count``."""
    text = response_text.strip()
    match = JSON_ARRAY_PATTERN.search(text)
    if match:
        try:
            values = json.loads(match.group())
            if isinstance(values, list) and values:
                parsed = [_clamp_sentiment(float(value)) for value in values[:count]]
                while len(parsed) < count:
                    parsed.append(0.0)
                return parsed
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    numbers = [_clamp_sentiment(float(value)) for value in SENTIMENT_PATTERN.findall(text)]
    if len(numbers) >= count:
        return numbers[:count]
    return numbers + [0.0] * (count - len(numbers))


def _score_headlines_batch_sync(ticker: str, articles: list[dict]) -> list[float]:
    """Score multiple headlines in one Ollama call."""
    if not articles:
        return []

    lines = []
    for index, article in enumerate(articles, start=1):
        summary = article.get("summary", "").strip()
        if summary:
            lines.append(f'{index}. Headline: {article["title"]}\n   Summary: {summary}')
        else:
            lines.append(f'{index}. Headline: {article["title"]}')

    llm = get_llm(temperature=0.0)
    prompt = (
        f"Score headline sentiment for {ticker} investors.\n"
        f"Return ONLY a JSON array of {len(articles)} numbers from -1.0 (very negative) "
        f"to +1.0 (very positive), in the same order as the headlines.\n\n"
        + "\n".join(lines)
    )
    response = llm.invoke(prompt)
    content = str(response.content if hasattr(response, "content") else response)
    return _parse_sentiment_batch(content, len(articles))


async def news_analyst_node(state: AgentState) -> dict:
    """Fetch RSS headlines and score sentiment for watchlist tickers."""
    new_errors: list[str] = []
    news_items: list[dict] = []
    batch_calls = 0
    entries = load_watchlist()
    tickers = [entry.ticker for entry in entries]
    feed_urls = [watchlist_google_news_feed(tickers)]
    feed_urls.extend(url for url in settings.rss_feed_list if url not in feed_urls)

    try:
        articles, feed_errors = await fetch_all_feeds(feed_urls)
        new_errors.extend(feed_errors)
    except Exception as exc:
        message = f"News fetch failed ({exc})"
        logger.warning(message)
        new_errors.append(message)
        return {"news_items": news_items, "errors": new_errors}

    headline_limit = settings.MAX_NEWS_HEADLINES_PER_TICKER

    for entry in entries:
        relevant = filter_relevant_articles(
            articles,
            ticker=entry.ticker,
            company_name=entry.name,
        )
        if not relevant:
            continue

        batch = relevant[:headline_limit]
        try:
            sentiments = await asyncio.to_thread(
                _score_headlines_batch_sync,
                entry.ticker,
                batch,
            )
            batch_calls += 1
            for article, sentiment in zip(batch, sentiments, strict=True):
                news_items.append(
                    {
                        "ticker": entry.ticker,
                        "headline": article["title"],
                        "source": article.get("source", ""),
                        "link": article.get("link", ""),
                        "published": article.get("published"),
                        "sentiment": sentiment,
                    }
                )
        except Exception as exc:
            message = f"{entry.ticker}: batched sentiment scoring failed ({exc})"
            logger.warning(message)
            new_errors.append(message)

    logger.info(
        "News analyst: %d scored items from %d Ollama batch calls",
        len(news_items),
        batch_calls,
    )
    return {"news_items": news_items, "errors": new_errors}
