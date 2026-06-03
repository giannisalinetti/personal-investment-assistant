"""Shared LangGraph state schema."""

from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Annotated, TypedDict


class AgentState(TypedDict, total=False):
    watchlist: list[str]
    discovered: list[dict]
    market_data: dict
    news_items: Annotated[list[dict], operator.add]
    signals: list[dict]
    suggestions: Annotated[list[dict], operator.add]
    watchlist_note: str | None
    notification_sent: bool
    run_timestamp: str
    run_type: str
    skipped: bool
    errors: Annotated[list[str], operator.add]


def initial_state(
    watchlist: list[str],
    *,
    run_type: str = "manual",
) -> AgentState:
    """Return a fresh AgentState for a graph run."""
    return AgentState(
        watchlist=watchlist,
        discovered=[],
        market_data={},
        news_items=[],
        signals=[],
        suggestions=[],
        watchlist_note=None,
        notification_sent=False,
        run_timestamp=datetime.now(timezone.utc).isoformat(),
        run_type=run_type,
        skipped=False,
        errors=[],
    )
