"""Discovery node — LLM correlated instrument suggestions with yfinance validation."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter

from src.config import ASSET_CLASS_LABELS, AssetClass, load_watchlist
from src.llm import get_llm
from src.skills import (
    activated_skill_names,
    format_monitor_skills_block,
    select_monitor_skills,
)
from src.state import AgentState
from src.tools.yfinance_tool import validate_ticker

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 3
JSON_ARRAY_PATTERN = re.compile(r"\[.*\]", re.DOTALL)


def _dominant_asset_class(entries: list) -> AssetClass:
    if not entries:
        return "stock"
    counts = Counter(entry.asset_class for entry in entries)
    return counts.most_common(1)[0][0]


def _discover_sync(
    watchlist_tickers: list[str],
    watchlist_names: list[str],
    asset_class: AssetClass,
) -> list[dict]:
    """Ask the LLM for correlated instruments (blocking)."""
    label = ASSET_CLASS_LABELS.get(asset_class, asset_class)
    class_hint = {
        "stock": "stocks (equities)",
        "etf": "ETFs (exchange-traded funds)",
        "etc": "ETCs (exchange-traded commodities)",
    }.get(asset_class, label)
    skills = select_monitor_skills(asset_classes={asset_class})
    skills_block = format_monitor_skills_block(skills)
    if skills:
        logger.info("Discovery skills: %s", activated_skill_names(skills))

    llm = get_llm(temperature=0.2)
    prompt_parts = [
        "You are a market research assistant. Given this watchlist, suggest up to "
        f"{MAX_SUGGESTIONS} related {class_hint} the user might want to monitor.",
        f"Prefer suggestions in the same asset class ({asset_class}).",
        f"Watchlist tickers: {', '.join(watchlist_tickers)}",
        f"Names: {', '.join(watchlist_names)}",
        "",
        "Return ONLY a JSON array. Each item must have keys: "
        'ticker, name, reason, confidence ("HIGH" or "MEDIUM"), '
        f'asset_class (must be "{asset_class}").',
        "Do not suggest tickers already in the watchlist.",
        "Keep reasons class-appropriate (e.g. exposure/theme for ETFs, commodity drivers for ETCs).",
    ]
    if skills_block:
        prompt_parts.extend(["", skills_block])
    response = llm.invoke("\n".join(prompt_parts))
    content = str(response.content if hasattr(response, "content") else response)
    match = JSON_ARRAY_PATTERN.search(content)
    if not match:
        return []
    raw = json.loads(match.group())
    if not isinstance(raw, list):
        return []
    return raw


async def discovery_node(state: AgentState) -> dict:
    """Suggest correlated instruments and validate tickers via yfinance."""
    new_errors: list[str] = []
    suggestions: list[dict] = []
    entries = load_watchlist()
    watchlist_tickers = {entry.ticker.upper() for entry in entries}
    dominant = _dominant_asset_class(entries)

    try:
        raw_suggestions = await asyncio.to_thread(
            _discover_sync,
            [entry.ticker for entry in entries],
            [entry.name for entry in entries],
            dominant,
        )
    except Exception as exc:
        message = f"Discovery LLM failed ({exc})"
        logger.warning(message)
        new_errors.append(message)
        return {"suggestions": suggestions, "discovered": suggestions, "errors": new_errors}

    candidates: list[dict] = []
    for item in raw_suggestions[:MAX_SUGGESTIONS]:
        ticker = str(item.get("ticker", "")).upper().strip()
        confidence = str(item.get("confidence", "LOW")).upper()
        if not ticker or ticker in watchlist_tickers:
            continue
        if confidence not in {"HIGH", "MEDIUM"}:
            continue
        asset_class = str(item.get("asset_class", dominant)).lower().strip()
        if asset_class not in {"stock", "etf", "etc"}:
            asset_class = dominant
        candidates.append(
            {
                "ticker": ticker,
                "name": str(item.get("name", ticker)),
                "reason": str(item.get("reason", "")),
                "type": "SUGGESTION",
                "confidence": confidence,
                "asset_class": asset_class,
            }
        )

    if candidates:
        validations = await asyncio.gather(
            *[validate_ticker(item["ticker"]) for item in candidates]
        )
        for item, valid in zip(candidates, validations, strict=True):
            if not valid:
                new_errors.append(f"Discovery: dropped invalid ticker {item['ticker']}")
                continue
            suggestions.append(item)

    logger.info("Discovery: %d validated suggestions", len(suggestions))
    return {
        "suggestions": suggestions,
        "discovered": suggestions,
        "errors": new_errors,
    }
