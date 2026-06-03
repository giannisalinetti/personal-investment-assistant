"""Rich terminal dashboard — read-only view of data/state.json."""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from src.config import settings
from src.nodes.notifier import format_suggestion_line
from src.state_persistence import load_state, state_age_hours

REFRESH_SECONDS = 10
SIGNAL_EMOJI = {"BUY": "🟢", "SELL": "🔴", "WATCH": "🟡", "HOLD": "⚪"}


def _signal_style(signal: str) -> str:
    return {
        "BUY": "green",
        "SELL": "red",
        "WATCH": "yellow",
        "HOLD": "white",
    }.get(signal, "white")


def _format_last_run(document: dict) -> str:
    last_run = document.get("last_run", "unknown")
    run_type = document.get("run_type", "manual")
    if document.get("skipped"):
        return f"{last_run} — skipped ({run_type})"
    return f"{last_run} — {run_type}"


def _render_dashboard(document: dict | None) -> Panel:
    if document is None:
        body = Text(
            "No state.json found. Run `uv run pia-graph` or wait for a scheduled pia-run.",
            style="yellow",
        )
        return Panel(body, title="Personal Investment Assistant", border_style="red")

    banner = Text()
    age = state_age_hours(document)
    if age is None:
        banner.append("⚠ State timestamp invalid\n", style="bold yellow")
    elif age > settings.ADVISOR_STALE_STATE_HOURS:
        banner.append(
            f"⚠ State is stale ({age:.1f}h old)\n",
            style="bold yellow",
        )

    header = Text.assemble(
        ("Model: ", "dim"),
        (document.get("model", settings.OLLAMA_MODEL), "cyan"),
        ("  │  Watchlist: ", "dim"),
        (str(document.get("watchlist_count", "—")), "cyan"),
        (" tickers\n", "dim"),
        ("Last run: ", "dim"),
        (_format_last_run(document), "white"),
    )

    signal_lines: list[Text] = []
    for signal in document.get("signals", []):
        emoji = SIGNAL_EMOJI.get(signal.get("signal", "HOLD"), "⚪")
        ticker = signal.get("ticker", "?")
        label = signal.get("signal", "HOLD")
        confidence = signal.get("confidence", "—")
        rationale = signal.get("rationale", "")
        line = Text()
        line.append(f"  {emoji} {ticker:<8} ", style="bold")
        line.append(f"{label:<5} ", style=_signal_style(label))
        line.append(f"{confidence:<6} ", style="dim")
        line.append(rationale)
        signal_lines.append(line)

    if not signal_lines:
        signal_lines.append(Text("  No signals in last run.", style="dim"))

    suggestions = document.get("suggestions", [])
    suggestion_lines = [Text(format_suggestion_line(item).strip()) for item in suggestions]
    if not suggestion_lines:
        suggestion_lines = [Text("  None", style="dim")]

    note = document.get("watchlist_note")
    note_text = Text(note if note else "None", style="white" if note else "dim")

    errors = document.get("errors", [])
    error_text = Text(
        "; ".join(errors) if errors else "none",
        style="yellow" if errors else "dim",
    )

    now = datetime.now(ZoneInfo(settings.TIMEZONE)).strftime("%H:%M %Z")
    footer = Text(f"Updated {now}  │  Refresh: {REFRESH_SECONDS}s  │  [q] quit", style="dim")

    body = Group(
        banner,
        header,
        Text(""),
        Text("Watchlist signals — last run", style="bold underline"),
        *signal_lines,
        Text(""),
        Text("💡 Suggested", style="bold"),
        *suggestion_lines,
        Text(""),
        Text("Watchlist note", style="bold"),
        note_text,
        Text(""),
        Text.assemble(("Errors: ", "bold"), error_text),
        Text(""),
        footer,
    )
    return Panel(body, title="Personal Investment Assistant", border_style="blue")


def _wait_for_quit(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            line = input()
        except EOFError:
            stop_event.set()
            return
        if line.strip().lower() == "q":
            stop_event.set()


def main() -> None:
    console = Console()
    stop_event = threading.Event()
    threading.Thread(target=_wait_for_quit, args=(stop_event,), daemon=True).start()

    console.print("[dim]Type q + Enter to quit. Monitor service keeps running independently.[/dim]\n")
    with Live(console=console, refresh_per_second=4, screen=True) as live:
        while not stop_event.is_set():
            live.update(_render_dashboard(load_state()))
            for _ in range(REFRESH_SECONDS * 4):
                if stop_event.is_set():
                    break
                time.sleep(0.25)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
