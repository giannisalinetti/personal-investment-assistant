"""Interactive advisor CLI — reasoning over data/state.json."""

from __future__ import annotations

import asyncio
import logging
import sys

from rich.console import Console

from src.advisor_history import append_exchange, clear_history, load_turns
from src.cli import command_parser
from src.config import load_watchlist
from src.logging_config import configure_logging
from src.advisor_scan import scan_status_message
from src.nodes.advisor import advisor_respond, resolve_advisor_targets
from src.nodes.notifier import DISCLAIMER
from src.state_persistence import load_state

configure_logging()
logger = logging.getLogger(__name__)
console = Console()

_REPL_QUIT = frozenset({"/quit", "/exit", "/q"})
_REPL_CLEAR = "/clear"
_REPL_BRIEF = "/brief"


def _parse_args() -> None:
    parser = command_parser(
        "pia-advisor",
        "Interactive Advisor REPL — reasoning over state.json with persisted history.",
        epilog=(
            "REPL commands:\n"
            "  /brief   Daily narrative brief\n"
            "  /clear   Reset persisted conversation history\n"
            "  /quit    Exit (also: /exit, /q)\n\n"
            "Or type any free-form investment question.\n\n"
            "Example:\n"
            "  uv run pia-advisor"
        ),
    )
    parser.parse_args()


async def _repl() -> None:
    watchlist = load_watchlist()
    history = load_turns()

    console.print("[bold]Personal Investment Assistant — Advisor[/bold]")
    console.print(DISCLAIMER)
    console.print()
    console.print(
        "Commands: [cyan]/brief[/cyan]  [cyan]/clear[/cyan]  [cyan]/quit[/cyan]  or type a question"
    )
    console.print(
        "[dim]Uses data/state.json, persisted history, live quotes, and fresh RSS headlines. "
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
        normalized = user_input.lower()
        if normalized in _REPL_QUIT:
            break
        if normalized == _REPL_CLEAR:
            clear_history()
            history = []
            console.print("[dim]Conversation history cleared.[/dim]\n")
            continue
        if normalized == _REPL_BRIEF:
            mode = "brief"
            question = ""
        else:
            mode = "ask"
            question = user_input

        state = load_state()
        targets, on_demand, scan = await resolve_advisor_targets(
            question=question,
            watchlist=watchlist,
            mode=mode,
        )
        if scan_message := scan_status_message(scan):
            console.print(f"[dim]{scan_message.capitalize()}…[/dim]")
        elif on_demand and on_demand.get("tickers"):
            tickers = ", ".join(on_demand["tickers"])
            console.print(f"[dim]Running on-demand analysis for {tickers}…[/dim]")
        elif targets:
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
            resolved=(targets, on_demand, scan),
        )
        history = append_exchange(user=user_input, assistant=answer)
        console.print()
        console.print(answer)
        console.print()


def main() -> None:
    _parse_args()
    try:
        asyncio.run(_repl())
    except KeyboardInterrupt:
        console.print()
    sys.exit(0)


if __name__ == "__main__":
    main()
