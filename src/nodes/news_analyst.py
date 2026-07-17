"""News analyst node — RSS fetch + single batched LLM sentiment scoring."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from src.config import AssetClass, WatchlistEntry, load_watchlist, settings
from src.llm import get_llm
from src.skills import (
    activated_skill_names,
    format_monitor_skills_block,
    select_monitor_skills,
)
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


def _score_headlines_batch_sync(
    scored_items: list[tuple[WatchlistEntry, dict]],
) -> list[float]:
    """Score all watchlist headlines in one Ollama call."""
    if not scored_items:
        return []

    lines = []
    for index, (entry, article) in enumerate(scored_items, start=1):
        summary = article.get("summary", "").strip()
        if summary:
            lines.append(
                f'{index}. [{entry.ticker}] Headline: {article["title"]}\n   Summary: {summary}'
            )
        else:
            lines.append(f'{index}. [{entry.ticker}] Headline: {article["title"]}')

    classes: set[AssetClass] = {entry.asset_class for entry, _ in scored_items}
    skills = select_monitor_skills(asset_classes=classes, include_news=True)
    skills_block = format_monitor_skills_block(skills)
    if skills:
        logger.info("News analyst skills: %s", activated_skill_names(skills))

    llm = get_llm(temperature=0.0)
    prompt_parts = [
        "Score headline sentiment for investors in each bracketed ticker.",
        "Score company/fund/commodity-relevant news for that ticker; ignore unrelated macro noise when possible.",
        f"Return ONLY a JSON array of {len(scored_items)} numbers from -1.0 (very negative) "
        f"to +1.0 (very positive), in the same order as the headlines.",
    ]
    if skills_block:
        prompt_parts.extend(["", skills_block])
    prompt_parts.extend(["", *lines])
    response = llm.invoke("\n".join(prompt_parts))
    content = str(response.content if hasattr(response, "content") else response)
    return _parse_sentiment_batch(content, len(scored_items))


async def news_analyst_node(state: AgentState) -> dict:
    """Fetch RSS headlines and score sentiment for watchlist tickers."""
    new_errors: list[str] = []
    news_items: list[dict] = []
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
    total_limit = settings.MAX_NEWS_HEADLINES_TOTAL
    scored_items: list[tuple[WatchlistEntry, dict]] = []

    for entry in entries:
        relevant = filter_relevant_articles(
            articles,
            ticker=entry.ticker,
            company_name=entry.name,
        )
        for article in relevant[:headline_limit]:
            scored_items.append((entry, article))
            if len(scored_items) >= total_limit:
                break
        if len(scored_items) >= total_limit:
            break

    if not scored_items:
        logger.info("News analyst: no relevant headlines to score")
        return {"news_items": news_items, "errors": new_errors}

    try:
        sentiments = await asyncio.to_thread(_score_headlines_batch_sync, scored_items)
        for (entry, article), sentiment in zip(scored_items, sentiments, strict=True):
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
        message = f"Batched sentiment scoring failed ({exc})"
        logger.warning(message)
        new_errors.append(message)

    logger.info(
        "News analyst: %d scored items from 1 Ollama batch call",
        len(news_items),
    )
    return {"news_items": news_items, "errors": new_errors}
