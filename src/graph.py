"""LangGraph definition — Increment 3: parallel fan-out, join, notifier."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.nodes.analyst import analyst_node
from src.nodes.discovery import discovery_node
from src.nodes.market_data import market_data_node
from src.nodes.news_analyst import news_analyst_node
from src.nodes.notifier import notifier_node
from src.nodes.supervisor import supervisor_node
from src.state import AgentState


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


def build_graph():
    """Build and compile the Increment 3 pipeline graph.

    Flow (markets open):
        START → supervisor → dispatch → [market_data, news_analyst, discovery]
              → analyst → notifier → END

    Flow (all exchanges closed):
        START → supervisor → END

    The three worker nodes run in parallel. Analyst waits for all three
    (join barrier) before synthesizing signals.
    """
    builder = StateGraph(AgentState)

    builder.add_node("supervisor", supervisor_node)
    builder.add_node("dispatch", dispatch_node)
    builder.add_node("market_data", market_data_node)
    builder.add_node("news_analyst", news_analyst_node)
    builder.add_node("discovery", discovery_node)
    builder.add_node("analyst", analyst_node)
    builder.add_node("notifier", notifier_node)

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
