"""RSS feed fetching via httpx + feedparser."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import feedparser
import httpx

logger = logging.getLogger(__name__)

NEWS_WINDOW_HOURS = 24


def watchlist_google_news_feed(tickers: list[str]) -> str:
    """Build a Google News RSS URL covering watchlist ticker symbols."""
    query = quote(" OR ".join(tickers))
    return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def ticker_google_news_feed(ticker: str, company_name: str | None = None) -> str:
    """Build a Google News RSS URL for one ticker (Advisor fresh-news lookup)."""
    terms = [ticker]
    if company_name:
        short_name = company_name.split(" Corp")[0].split(" Inc")[0].strip()
        if short_name and short_name.lower() not in ticker.lower():
            terms.append(short_name)
    query = quote(" OR ".join(terms))
    return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


async def fetch_feed(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    window_hours: int = NEWS_WINDOW_HOURS,
) -> list[dict]:
    """Fetch and parse one RSS feed URL."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=20.0, follow_redirects=True)
    try:
        response = await client.get(url)
        response.raise_for_status()
        parsed = feedparser.parse(response.text)
        articles: list[dict] = []
        for entry in parsed.entries:
            published = _entry_datetime(entry)
            if published and not _is_within_window(published, window_hours):
                continue
            articles.append(
                {
                    "title": entry.get("title", "").strip(),
                    "summary": entry.get("summary", entry.get("description", "")).strip(),
                    "link": entry.get("link", ""),
                    "published": published.isoformat() if published else None,
                    "source": parsed.feed.get("title", url),
                }
            )
        return articles
    finally:
        if owns_client:
            await client.aclose()


async def fetch_all_feeds(
    urls: list[str],
    *,
    window_hours: int = NEWS_WINDOW_HOURS,
) -> tuple[list[dict], list[str]]:
    """Fetch articles from all configured RSS feeds.

    Returns (articles, errors). Individual feed failures are non-fatal.
    """
    articles: list[dict] = []
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        for url in urls:
            try:
                feed_articles = await fetch_feed(url, client=client, window_hours=window_hours)
                articles.extend(feed_articles)
                logger.info("Fetched %d recent articles from %s", len(feed_articles), url)
            except Exception as exc:
                message = f"RSS feed failed ({url}): {exc}"
                logger.warning(message)
                errors.append(message)
    return articles, errors


async def fetch_ticker_headlines(
    ticker: str,
    company_name: str,
    *,
    window_hours: int,
    limit: int,
) -> tuple[list[dict], list[str]]:
    """Fetch fresh Google News headlines for a single ticker."""
    url = ticker_google_news_feed(ticker, company_name)
    try:
        articles = await fetch_feed(url, window_hours=window_hours)
        return articles[:limit], []
    except Exception as exc:
        message = f"Fresh news fetch failed for {ticker}: {exc}"
        logger.warning(message)
        return [], [message]


def filter_relevant_articles(
    articles: list[dict],
    *,
    ticker: str,
    company_name: str,
) -> list[dict]:
    """Keep articles mentioning the ticker symbol or company name."""
    ticker_upper = ticker.upper()
    name_lower = company_name.lower()
    relevant: list[dict] = []
    for article in articles:
        haystack = f"{article.get('title', '')} {article.get('summary', '')}".upper()
        if ticker_upper in haystack or name_lower in haystack.lower():
            relevant.append(article)
    return relevant


def _entry_datetime(entry: object) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                return dt.astimezone(timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _is_within_window(published: datetime, window_hours: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    return published >= cutoff
