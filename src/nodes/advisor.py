"""Advisor node — on-demand reasoning over persisted Monitor state + fresh news."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

from urllib.parse import quote

from src.advisor_on_demand import (
    analyze_adhoc_tickers,
    build_adhoc_entries,
    format_on_demand_block,
)
from src.advisor_scan import (
    IndicatorScanResult,
    format_scan_block,
    run_indicator_scan,
    scan_status_message,
)
from src.config import WatchlistEntry, settings
from src.tools.ticker_extract import extract_adhoc_tickers
from src.llm import get_advisor_llm
from src.state_persistence import stale_state_warning
from src.tools.fundamentals_tool import fetch_fundamentals_batch
from src.tools.news_fetcher import fetch_ticker_headlines, filter_relevant_articles
from src.tools.quote_tool import fetch_quotes

logger = logging.getLogger(__name__)

BRIEF_PROMPT = """Produce a daily brief for my watchlist covering:
1. Macro themes that matter for MY tickers this week (not generic market commentary)
2. Top 2–3 conflicts or alignments across the watchlist signals
3. What to watch before the next scheduled Monitor run

Use Monitor data and fresh headlines below. Cite specific headlines when explaining recent moves. State assumptions explicitly."""

_RECENT_NEWS_HINTS = re.compile(
    r"\b(news|headline|announce|recent|today|yesterday|last\s+(few\s+)?days|"
    r"this\s+week|why|rise|rally|surge|jump|fall|drop|selloff|move|moving)\b",
    re.IGNORECASE,
)


def fresh_news_targets(
    *,
    question: str,
    watchlist: list[WatchlistEntry],
    mode: str,
) -> list[WatchlistEntry]:
    """Return watchlist entries to fetch live headlines for (sync subset)."""
    if mode == "brief":
        return watchlist

    mentioned = _entries_mentioned_in_text(question, watchlist)
    if mentioned:
        return mentioned

    adhoc = extract_adhoc_tickers(question, watchlist)[: settings.ADVISOR_ADHOC_MAX_TICKERS]
    if adhoc:
        return [WatchlistEntry(ticker=ticker, name=ticker) for ticker in adhoc]

    if _RECENT_NEWS_HINTS.search(question):
        return watchlist
    return []


def _dedupe_entries(entries: list[WatchlistEntry]) -> list[WatchlistEntry]:
    seen: set[str] = set()
    unique: list[WatchlistEntry] = []
    for entry in entries:
        key = entry.ticker.upper()
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


async def _maybe_analyze_explicit_tickers(
    question: str,
    watchlist: list[WatchlistEntry],
) -> tuple[list[WatchlistEntry], dict | None]:
    explicit = extract_adhoc_tickers(question, watchlist)[: settings.ADVISOR_ADHOC_MAX_TICKERS]
    if not explicit:
        return [], None
    entries = await build_adhoc_entries(explicit)
    analysis = await analyze_adhoc_tickers(entries)
    return entries, analysis


async def resolve_advisor_targets(
    *,
    question: str,
    watchlist: list[WatchlistEntry],
    mode: str,
) -> tuple[list[WatchlistEntry], dict | None, IndicatorScanResult | None]:
    """Resolve headline/quote targets, on-demand analysis, and indicator scans."""
    if mode == "brief":
        return watchlist, None, None

    watchlist_mentioned = _entries_mentioned_in_text(question, watchlist)
    scan: IndicatorScanResult | None = None
    on_demand: dict | None = None
    explicit_entries: list[WatchlistEntry] = []

    parallel: list[tuple[str, asyncio.Task]] = []
    if settings.ADVISOR_SCAN_ENABLED:
        parallel.append(("scan", asyncio.create_task(run_indicator_scan(question, watchlist))))
    if settings.ADVISOR_ADHOC_ANALYSIS:
        parallel.append(
            ("adhoc", asyncio.create_task(_maybe_analyze_explicit_tickers(question, watchlist)))
        )

    if parallel:
        results = await asyncio.gather(*(task for _, task in parallel))
        for (label, _), result in zip(parallel, results, strict=True):
            if label == "scan":
                scan = result
            else:
                explicit_entries, on_demand = result

    if watchlist_mentioned or explicit_entries:
        query_entries = _dedupe_entries(watchlist_mentioned + explicit_entries)
    elif _RECENT_NEWS_HINTS.search(question):
        query_entries = watchlist
    else:
        query_entries = []

    return query_entries, on_demand, scan


def _format_watchlist_block(entries: list[WatchlistEntry]) -> str:
    lines = []
    for entry in entries:
        lines.append(
            f"- {entry.ticker}: {entry.name} "
            f"(RSI alerts {entry.rsi_oversold:g}/{entry.rsi_overbought:g})"
        )
    return "\n".join(lines)


def _format_state_block(state: dict) -> str:
    payload = {
        "last_run": state.get("last_run"),
        "run_type": state.get("run_type"),
        "skipped": state.get("skipped"),
        "watchlist_note": state.get("watchlist_note"),
        "signals": state.get("signals", []),
        "suggestions": state.get("suggestions", []),
        "errors": state.get("errors", []),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _state_for_prompt(
    state: dict,
    *,
    mode: str,
    question: str,
    watchlist: list[WatchlistEntry],
) -> dict:
    """Trim Monitor state for /ask when the question targets specific tickers."""
    if mode == "brief":
        return state

    mentioned = _entries_mentioned_in_text(question, watchlist)
    if not mentioned:
        return state

    tickers = {entry.ticker.upper() for entry in mentioned}
    return {
        "last_run": state.get("last_run"),
        "run_type": state.get("run_type"),
        "skipped": state.get("skipped"),
        "watchlist_note": state.get("watchlist_note"),
        "signals": [
            signal
            for signal in state.get("signals", [])
            if str(signal.get("ticker", "")).upper() in tickers
        ],
        "suggestions": [],
        "errors": state.get("errors", []),
    }


def _entries_mentioned_in_text(text: str, watchlist: list[WatchlistEntry]) -> list[WatchlistEntry]:
    """Match watchlist tickers or company names mentioned in the user question."""
    matched: list[WatchlistEntry] = []
    text_upper = text.upper()
    text_lower = text.lower()
    for entry in watchlist:
        ticker = entry.ticker.upper()
        base_ticker = ticker.split(".")[0]
        if (
            re.search(rf"\b{re.escape(base_ticker)}\b", text_upper)
            or ticker in text_upper
            or entry.name.lower() in text_lower
        ):
            matched.append(entry)
    return matched


def _format_fresh_headlines_block(headlines_by_ticker: dict[str, list[dict]]) -> str:
    if not headlines_by_ticker:
        return "No fresh headlines fetched for this question."

    lines = [
        f"(Google News RSS, last {settings.ADVISOR_NEWS_WINDOW_HOURS}h — fetched on demand, "
        "not from the last Monitor run)",
    ]
    for ticker, articles in headlines_by_ticker.items():
        lines.append(f"\n[{ticker}]")
        if not articles:
            lines.append("  (no headlines in window)")
            continue
        for index, article in enumerate(articles, start=1):
            title = article.get("title", "").strip()
            published = article.get("published", "")
            source = article.get("source", "")
            meta = " — ".join(part for part in (published, source) if part)
            lines.append(f"  {index}. {title}" + (f" ({meta})" if meta else ""))
    return "\n".join(lines)


def _format_live_quotes_block(quotes_by_ticker: dict[str, dict]) -> str:
    if not quotes_by_ticker:
        return "No live quotes fetched."

    lines = ["(yfinance — fetched on demand, not from the last Monitor run)"]
    for ticker, quote in quotes_by_ticker.items():
        price = quote.get("price")
        change_pct = quote.get("change_pct")
        currency = quote.get("currency", "")
        as_of = quote.get("as_of", "")
        if price is None:
            lines.append(f"- {ticker}: unavailable")
            continue
        change_text = f", {change_pct:+.2f}% vs prior close" if change_pct is not None else ""
        volume = quote.get("volume")
        volume_text = f", vol {volume:,}" if volume is not None else ""
        lines.append(
            f"- {ticker}: {price:.2f} {currency}{change_text}{volume_text} (as of {as_of})"
        )
    return "\n".join(lines)


def _format_valuation_block(fundamentals_by_ticker: dict[str, dict]) -> str:
    if not fundamentals_by_ticker:
        return "No valuation metrics fetched."

    lines = [
        "(yfinance — trailing P/E, forward P/E, PEG; fetched on demand, Advisor only. "
        "Often unavailable for ETFs and some international symbols.)",
    ]
    for ticker, metrics in fundamentals_by_ticker.items():
        trailing = metrics.get("trailing_pe")
        forward = metrics.get("forward_pe")
        peg = metrics.get("peg_ratio")
        as_of = metrics.get("as_of", "")
        parts: list[str] = []
        parts.append(f"trailing P/E {trailing:.1f}" if trailing is not None else "trailing P/E —")
        parts.append(f"forward P/E {forward:.1f}" if forward is not None else "forward P/E —")
        parts.append(f"PEG {peg:.2f}" if peg is not None else "PEG —")
        lines.append(f"- {ticker}: {', '.join(parts)} (as of {as_of})")
    return "\n".join(lines)


def _fundamentals_tickers(
    *,
    mode: str,
    question: str,
    watchlist: list[WatchlistEntry],
    entries: list[WatchlistEntry],
) -> list[str]:
    if not settings.ADVISOR_FETCH_FUNDAMENTALS:
        return []
    if mode == "brief":
        return [entry.ticker for entry in watchlist]
    if entries:
        return [entry.ticker for entry in entries]
    mentioned = _entries_mentioned_in_text(question, watchlist)
    return [entry.ticker for entry in mentioned]


async def _fetch_valuation_metrics(
    *,
    mode: str,
    question: str,
    watchlist: list[WatchlistEntry],
    entries: list[WatchlistEntry],
) -> tuple[dict[str, dict], list[str]]:
    tickers = _fundamentals_tickers(
        mode=mode,
        question=question,
        watchlist=watchlist,
        entries=entries,
    )
    if not tickers:
        return {}, []
    fundamentals, errors = await fetch_fundamentals_batch(tickers)
    logger.info("Advisor valuation metrics: %s", list(fundamentals))
    return fundamentals, errors


async def _fetch_live_quotes(entries: list[WatchlistEntry]) -> tuple[dict[str, dict], list[str]]:
    if not settings.ADVISOR_FETCH_QUOTES or not entries:
        return {}, []
    tickers = [entry.ticker for entry in entries]
    quotes, errors = await fetch_quotes(tickers)
    logger.info("Advisor live quotes: %s", list(quotes))
    return quotes, errors


def _yahoo_finance_url(ticker: str) -> str:
    return f"https://finance.yahoo.com/quote/{ticker}"


def _google_news_search_url(ticker: str, company_name: str) -> str:
    query = quote(f"{ticker} stock")
    return f"https://news.google.com/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def format_useful_links_section(
    *,
    fresh_headlines: dict[str, list[dict]],
    entries: list[WatchlistEntry],
    max_headline_links: int = 6,
) -> str | None:
    """Build a footer with headline URLs and quote/news search links."""
    if not fresh_headlines and not entries:
        return None

    lines = ["📎 Useful links"]
    headline_links: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    for ticker, articles in fresh_headlines.items():
        for article in articles:
            url = str(article.get("link", "")).strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title = str(article.get("title", ticker)).strip()
            if len(title) > 90:
                title = f"{title[:87]}…"
            headline_links.append((title, url))
            if len(headline_links) >= max_headline_links:
                break
        if len(headline_links) >= max_headline_links:
            break

    if headline_links:
        lines.append("")
        lines.append("Headlines")
        for title, url in headline_links:
            lines.append(f"  • {title}")
            lines.append(f"    {url}")

    if entries:
        lines.append("")
        lines.append("Charts & further reading")
        for entry in entries:
            lines.append(f"  • {entry.ticker} quote — {_yahoo_finance_url(entry.ticker)}")
            lines.append(
                f"  • {entry.ticker} news — {_google_news_search_url(entry.ticker, entry.name)}"
            )

    if len(lines) == 1:
        return None
    return "\n".join(lines)


async def _fetch_fresh_headlines(entries: list[WatchlistEntry]) -> tuple[dict[str, list[dict]], list[str]]:
    """Fetch live Google News RSS headlines for the given watchlist entries."""
    if not entries:
        return {}, []

    headlines_by_ticker: dict[str, list[dict]] = {}
    errors: list[str] = []
    window = settings.ADVISOR_NEWS_WINDOW_HOURS
    limit = settings.ADVISOR_NEWS_HEADLINES_PER_TICKER

    results = await asyncio.gather(
        *[
            fetch_ticker_headlines(
                entry.ticker,
                entry.name,
                window_hours=window,
                limit=limit,
            )
            for entry in entries
        ]
    )

    for entry, (articles, fetch_errors) in zip(entries, results, strict=True):
        errors.extend(fetch_errors)
        relevant = filter_relevant_articles(
            articles,
            ticker=entry.ticker,
            company_name=entry.name,
        )
        headlines_by_ticker[entry.ticker] = relevant[:limit]
        logger.info(
            "Advisor fresh news: %s — %d headlines",
            entry.ticker,
            len(headlines_by_ticker[entry.ticker]),
        )

    return headlines_by_ticker, errors


def _build_prompt(
    *,
    question: str,
    state: dict,
    watchlist: list[WatchlistEntry],
    history: list[dict],
    mode: str,
    fresh_headlines: dict[str, list[dict]],
    live_quotes: dict[str, dict],
    valuation: dict[str, dict],
    on_demand: dict | None,
    scan: IndicatorScanResult | None,
) -> str:
    system = (
        "You are a personal investment advisor assistant. You help the user think through "
        "investment decisions — you never execute trades and have no portfolio access.\n"
        "Rules:\n"
        "- Latest Monitor run covers the configured watchlist only\n"
        "- Indicator scan results include a pre-computed exact_leader — always state that ticker and value\n"
        "- On-demand analysis covers explicitly mentioned tickers outside the watchlist\n"
        "- Ground answers in Monitor data, Indicator scan, On-demand analysis, Valuation metrics, "
        "Live quotes, and Fresh headlines\n"
        "- Use Valuation metrics (trailing P/E, forward P/E, PEG) for expensive/cheap/valuation questions\n"
        "- Prefer citing specific headlines for 'why did X move' questions\n"
        "- Do not invent prices, RSI, P/E, PEG values, or headlines not present in the context\n"
        "- Note when P/E or PEG is unavailable (common for ETFs); do not substitute guesses\n"
        "- Frame output as considerations and trade-offs, not direct buy/sell orders\n"
        "- State assumptions explicitly when data is incomplete\n"
        "- Be concise — lead with the direct answer, then supporting detail"
    )
    prompt_state = _state_for_prompt(state, mode=mode, question=question, watchlist=watchlist)
    watchlist_block = watchlist
    if mode == "ask":
        mentioned = _entries_mentioned_in_text(question, watchlist)
        if mentioned:
            watchlist_block = mentioned

    parts = [
        system,
        "",
        "=== Watchlist ===",
        _format_watchlist_block(watchlist_block),
        "",
        "=== Latest Monitor run ===",
        _format_state_block(prompt_state),
        "",
        "=== Indicator scan (computed) ===",
        format_scan_block(scan),
        "",
        "=== On-demand analysis (explicit tickers) ===",
        format_on_demand_block(on_demand),
        "",
        "=== Live quotes ===",
        _format_live_quotes_block(live_quotes),
        "",
        "=== Valuation metrics (Advisor only) ===",
        _format_valuation_block(valuation),
        "",
        "=== Fresh headlines (live RSS) ===",
        _format_fresh_headlines_block(fresh_headlines),
    ]
    if history:
        history_limit = 4 if mode == "ask" else 6
        parts.extend(["", "=== Conversation history ==="])
        for turn in history[-history_limit:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            parts.append(f"{role.upper()}: {content}")

    if mode == "brief":
        parts.extend(["", "=== Task ===", BRIEF_PROMPT])
    else:
        parts.extend(["", "=== User question ===", question])

    return "\n".join(parts)


def _invoke_advisor_sync(prompt: str) -> str:
    llm = get_advisor_llm()
    response = llm.invoke(prompt)
    return str(response.content if hasattr(response, "content") else response).strip()


async def advisor_respond(
    *,
    question: str,
    state: dict | None,
    watchlist: list[WatchlistEntry],
    history: list[dict] | None = None,
    mode: str = "ask",
    resolved: tuple[list[WatchlistEntry], dict | None, IndicatorScanResult | None] | None = None,
) -> str:
    """Single entry point for Advisor LLM calls."""
    history = history or []
    warning = stale_state_warning(state)
    if state is None:
        return warning or "Monitor state unavailable."

    if resolved is None:
        entries, on_demand, scan = await resolve_advisor_targets(
            question=question,
            watchlist=watchlist,
            mode=mode,
        )
    else:
        entries, on_demand, scan = resolved
    link_entries = entries or _entries_mentioned_in_text(question, watchlist)
    quote_entries = link_entries if settings.ADVISOR_FETCH_QUOTES else []

    t0 = time.perf_counter()
    headlines_result, quotes_result, valuation_result = await asyncio.gather(
        _fetch_fresh_headlines(entries),
        _fetch_live_quotes(quote_entries),
        _fetch_valuation_metrics(
            mode=mode,
            question=question,
            watchlist=watchlist,
            entries=entries,
        ),
    )
    fetch_seconds = time.perf_counter() - t0
    fresh_headlines, fetch_errors = headlines_result
    live_quotes, quote_errors = quotes_result
    valuation, fundamentals_errors = valuation_result

    prompt = _build_prompt(
        question=question,
        state=state,
        watchlist=watchlist,
        history=history,
        mode=mode,
        fresh_headlines=fresh_headlines,
        live_quotes=live_quotes,
        valuation=valuation,
        on_demand=on_demand,
        scan=scan,
    )
    logger.info(
        "Advisor invoke mode=%s tickers_fetched=%s adhoc=%s scan=%s prompt_chars=%d",
        mode,
        list(fresh_headlines),
        on_demand.get("tickers") if on_demand else [],
        scan.leader.ticker if scan else None,
        len(prompt),
    )
    try:
        llm_start = time.perf_counter()
        answer = await asyncio.to_thread(_invoke_advisor_sync, prompt)
        llm_seconds = time.perf_counter() - llm_start
    except Exception as exc:
        logger.exception("Advisor LLM failed: %s", exc)
        return f"Advisor request failed ({exc}). Check Ollama is running."

    logger.info(
        "Advisor timing mode=%s fetch=%.1fs llm=%.1fs prompt_chars=%d reasoning=%s",
        mode,
        fetch_seconds,
        llm_seconds,
        len(prompt),
        settings.OLLAMA_ADVISOR_REASONING,
    )

    prefix_parts: list[str] = []
    if warning:
        prefix_parts.append(f"⚠️ {warning}")
    if fetch_errors:
        prefix_parts.append("⚠️ Some headline feeds failed: " + "; ".join(fetch_errors[:3]))
    if quote_errors:
        prefix_parts.append("⚠️ Some quote fetches failed: " + "; ".join(quote_errors[:3]))
    if fundamentals_errors:
        prefix_parts.append(
            "⚠️ Some valuation metric fetches failed: " + "; ".join(fundamentals_errors[:3])
        )
    if on_demand and on_demand.get("signals"):
        tickers = ", ".join(on_demand["tickers"])
        prefix_parts.append(f"ℹ️ On-demand analysis fetched for {tickers}.")
    if on_demand and on_demand.get("errors"):
        prefix_parts.append(
            "⚠️ On-demand analysis errors: " + "; ".join(on_demand["errors"][:3])
        )
    if scan:
        prefix_parts.append(
            f"ℹ️ Indicator scan complete — {scan.leader.ticker} has the "
            f"{'highest' if scan.direction == 'highest' else 'lowest'} "
            f"{scan.metric_label} ({scan.leader.value:.1f}) in scan universe."
        )
    if entries and not any(fresh_headlines.values()):
        prefix_parts.append(
            f"⚠️ No headlines found in the last {settings.ADVISOR_NEWS_WINDOW_HOURS}h "
            f"for {', '.join(e.ticker for e in entries)}."
        )

    if prefix_parts:
        answer = "\n\n".join(prefix_parts) + "\n\n" + answer

    if scan:
        answer = f"{answer.rstrip()}\n\n---\n\n{scan.exact_answer_block()}"

    links = format_useful_links_section(fresh_headlines=fresh_headlines, entries=link_entries)
    if links:
        answer = f"{answer.rstrip()}\n\n---\n\n{links}"
    return answer
