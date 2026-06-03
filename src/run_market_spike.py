"""Manual spike: watchlist -> market data -> technical signals."""

from __future__ import annotations

import asyncio
import logging
import sys

from rich.console import Console
from rich.table import Table

from src.config import load_watchlist, settings
from src.logging_config import configure_logging
from src.nodes.analyst import analyst_node
from src.nodes.market_data import market_data_node
from src.state import initial_state

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


async def run_spike() -> int:
    """Load watchlist, fetch data, compute signals, and print a summary table."""
    entries = load_watchlist()
    tickers = [entry.ticker for entry in entries]
    state = initial_state(tickers, run_type="manual")

    console.print(f"[bold]Personal Investment Assistant[/bold] — market data spike")
    console.print(f"Watchlist: {', '.join(tickers)}\n")

    market_update = await market_data_node(state)
    state.update(market_update)

    analyst_update = analyst_node(state)
    state.update(analyst_update)

    table = Table(title="Watchlist signals (technical only)")
    table.add_column("Ticker")
    table.add_column("Close")
    table.add_column("Signal")
    table.add_column("Confidence")
    table.add_column("Strength")
    table.add_column("Rationale")

    for signal in state.get("signals", []):
        ticker = signal["ticker"]
        payload = state["market_data"].get(ticker, {})
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

    errors = state.get("errors", [])
    if errors:
        console.print("\n[bold yellow]Errors[/bold yellow]")
        for error in errors:
            console.print(f"  • {error}")
        return 1

    return 0


def main() -> None:
    exit_code = asyncio.run(run_spike())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
