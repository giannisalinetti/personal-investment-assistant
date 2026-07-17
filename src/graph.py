"""LangGraph definition — Increment 3: parallel fan-out, join, notifier."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.nodes.analyst import analyst_node
from src.nodes.discovery import discovery_node
from src.nodes.market_data import market_data_node
from src.nodes.news_analyst import news_analyst_node
from src.nodes.notifier import notifier_node
from src.nodes.supervisor import supervisor_node
from src.state import AgentState
from src.telemetry import start_span


def route_after_supervisor(state: AgentState) -> str:
    """Conditional edge: skip pipeline when all watchlist exchanges are closed."""
    if state.get("skipped"):
        return "skip"
    return "continue"


def dispatch_node(state: AgentState) -> dict:
    """Pass-through node — fan-out happens on the conditional edge after this."""
    return {}


def fan_out_to_workers(state: AgentState) -> list[Send]:
    """Parallel fan-out via Send API (Increment 3)."""
    return [
        Send("market_data", state),
        Send("news_analyst", state),
        Send("discovery", state),
    ]


def _wrap_node(name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap an async graph node with an OpenTelemetry span."""

    async def wrapped(state: AgentState) -> dict:
        with start_span(f"pia.graph.{name}", attributes={"pia.graph.node": name}):
            result = fn(state)
            if isinstance(result, Awaitable):
                return await result
            return result

    return wrapped


def build_graph():
    """Build and compile the Increment 3 pipeline graph.

    Flow (markets open):
        START → supervisor → dispatch → [market_data, news_analyst, discovery]
              → analyst → notifier → END

    Flow (all exchanges closed):
        START → supervisor → END
    """
    builder = StateGraph(AgentState)

    builder.add_node("supervisor", _wrap_node("supervisor", supervisor_node))
    builder.add_node("dispatch", dispatch_node)
    builder.add_node("market_data", _wrap_node("market_data", market_data_node))
    builder.add_node("news_analyst", _wrap_node("news_analyst", news_analyst_node))
    builder.add_node("discovery", _wrap_node("discovery", discovery_node))
    builder.add_node("analyst", _wrap_node("analyst", analyst_node))
    builder.add_node("notifier", _wrap_node("notifier", notifier_node))

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "continue": "dispatch",
            "skip": END,
        },
    )
    builder.add_conditional_edges(
        "dispatch",
        fan_out_to_workers,
        ["market_data", "news_analyst", "discovery"],
    )
    builder.add_edge("market_data", "analyst")
    builder.add_edge("news_analyst", "analyst")
    builder.add_edge("discovery", "analyst")
    builder.add_edge("analyst", "notifier")
    builder.add_edge("notifier", END)

    return builder.compile()


graph = build_graph()
