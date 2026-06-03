"""Run the LangGraph pipeline (Increment 3) and print results."""

from __future__ import annotations

import asyncio
import logging
import sys

from rich.console import Console
from rich.table import Table

from src.config import load_watchlist, settings
from src.graph import graph
from src.logging_config import configure_logging
from src.nodes.notifier import format_notification, should_notify
from src.state import initial_state
from src.state_persistence import persist_state

configure_logging()
logger = logging.getLogger(__name__)
console = Console()


def _signal_style(signal: str) -> str:
    return {
        "BUY": "green",
        "SELL": "red",
        "WATCH": "yellow",
        "HOLD": "white",
    }.get(signal, "white")


def _print_results(final_state: dict) -> int:
    if final_state.get("skipped"):
        console.print("[bold yellow]Run skipped[/bold yellow] — all watchlist exchanges closed today.")
        console.print("Logged to logs/scheduler.log")
        console.print("Graph path: START → supervisor → END")
        return 0

    table = Table(title="Watchlist signals (technical + news)")
    table.add_column("Ticker")
    table.add_column("Close")
    table.add_column("Signal")
    table.add_column("Confidence")
    table.add_column("Strength")
    table.add_column("Rationale")

    market_data = final_state.get("market_data", {})
    for signal in final_state.get("signals", []):
        ticker = signal["ticker"]
        payload = market_data.get(ticker, {})
        close = payload.get("snapshot", {}).get("close")
        close_text = f"{close:.2f}" if close is not None else "—"
        table.add_row(
            ticker,
            close_text,
            f"[{_signal_style(signal['signal'])}]{signal['signal']}[/]",
            signal["confidence"],
            f"{signal['strength']:.2f}",
            signal["rationale"],
        )

    console.print(table)

    suggestions = final_state.get("suggestions", [])
    if suggestions:
        console.print("\n[bold]Discovery suggestions[/bold]")
        for item in suggestions:
            console.print(
                f"  • {item['ticker']} ({item['confidence']}) — {item.get('reason', item.get('name', ''))}"
            )

    watchlist_note = final_state.get("watchlist_note")
    if watchlist_note:
        console.print(f"\n[bold]Watchlist note[/bold]: {watchlist_note}")

    news_count = len(final_state.get("news_items", []))
    console.print(f"\nNews items scored: {news_count}")

    if should_notify(final_state):
        console.print("\n[bold]Notification preview[/bold]")
        console.print(format_notification(final_state))
    else:
        console.print("\n[dim]No notification sent (nothing met send criteria)[/dim]")

    if final_state.get("notification_sent"):
        console.print("[green]notification_sent=True[/green]")

    errors = final_state.get("errors", [])
    if errors:
        console.print("\n[bold yellow]Non-fatal errors[/bold yellow]")
        for error in errors:
            console.print(f"  • {error}")
    return 0


async def invoke_graph(*, run_type: str = "manual") -> dict:
    """Invoke the compiled LangGraph and return final state."""
    entries = load_watchlist()
    tickers = [entry.ticker for entry in entries]
    state = initial_state(tickers, run_type=run_type)

    logger.info("Invoking graph.ainvoke() run_type=%s tickers=%s", run_type, tickers)
    final_state = await graph.ainvoke(state)
    logger.info(
        "Graph complete: skipped=%s signals=%d suggestions=%d news=%d errors=%d",
        final_state.get("skipped"),
        len(final_state.get("signals", [])),
        len(final_state.get("suggestions", [])),
        len(final_state.get("news_items", [])),
        len(final_state.get("errors", [])),
    )
    return final_state


async def run_graph(*, run_type: str = "manual") -> dict:
    """Invoke the graph with dev CLI banner output."""
    entries = load_watchlist()
    tickers = [entry.ticker for entry in entries]

    console.print("[bold]Personal Investment Assistant[/bold] — LangGraph Increment 3")
    console.print(f"Model: {settings.OLLAMA_MODEL} @ {settings.OLLAMA_BASE_URL}")
    console.print(
        "Flow: START → supervisor → dispatch → "
        "[market_data | news_analyst | discovery] → analyst → notifier → END",
        markup=False,
    )
    console.print(f"Watchlist: {', '.join(tickers)}\n")

    return await invoke_graph(run_type=run_type)


def main() -> None:
    final_state = asyncio.run(run_graph())
    state_path = persist_state(final_state)
    console.print(f"\n[dim]State persisted to {state_path}[/dim]")
    exit_code = _print_results(final_state)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
