"""Interactive advisor CLI — reasoning over data/state.json."""

from __future__ import annotations

import asyncio
import logging
import sys

from rich.console import Console

from src.config import load_watchlist
from src.logging_config import configure_logging
from src.nodes.advisor import advisor_respond, fresh_news_targets
from src.nodes.notifier import DISCLAIMER
from src.state_persistence import load_state

configure_logging()
logger = logging.getLogger(__name__)
console = Console()


async def _repl() -> None:
    watchlist = load_watchlist()
    history: list[dict] = []

    console.print("[bold]Personal Investment Assistant — Advisor[/bold]")
    console.print(DISCLAIMER)
    console.print()
    console.print("Commands: [cyan]brief[/cyan]  [cyan]quit[/cyan]  or type a question")
    console.print(
        "[dim]Uses data/state.json plus live Google News RSS for mentioned tickers. "
        "Reasoning ON — expect 30s–3min.[/dim]\n"
    )

    while True:
        try:
            user_input = console.input("[bold green]ask>[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit", "q"}:
            break
        if user_input.lower() == "brief":
            mode = "brief"
            question = ""
        else:
            mode = "ask"
            question = user_input

        state = load_state()
        targets = fresh_news_targets(question=question, watchlist=watchlist, mode=mode)
        if targets:
            tickers = ", ".join(entry.ticker for entry in targets)
            console.print(f"[dim]Fetching fresh headlines for {tickers}…[/dim]")
        else:
            console.print("[dim]Thinking…[/dim]")
        answer = await advisor_respond(
            question=question,
            state=state,
            watchlist=watchlist,
            history=history,
            mode=mode,
        )
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": answer})
        console.print()
        console.print(answer)
        console.print()


def main() -> None:
    try:
        asyncio.run(_repl())
    except KeyboardInterrupt:
        console.print()
    sys.exit(0)


if __name__ == "__main__":
    main()
