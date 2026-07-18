"""Scheduled one-shot entry point — invoke graph, persist state, exit."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from src.cli import command_parser
from src.logging_config import configure_logging
from src.proactive_brief import maybe_send_proactive_brief
from src.run_graph import invoke_graph
from src.state_persistence import persist_state

configure_logging()
logger = logging.getLogger(__name__)

VALID_RUN_TYPES = ("pre_market", "midday", "end_of_day", "manual")


def _parse_args() -> argparse.Namespace:
    parser = command_parser(
        "pia-run",
        "Run the Monitor pipeline once, persist state.json, and exit.",
        epilog=(
            "Used for one-shot Monitor runs (Compose pia-run, K8s CronJobs, Ofelia, or manual).\n"
            "May send a proactive Advisor brief after pre_market when enabled.\n\n"
            "Examples:\n"
            "  uv run pia-run --run-type pre_market\n"
            "  uv run pia-run --run-type manual"
        ),
    )
    parser.add_argument(
        "--run-type",
        choices=VALID_RUN_TYPES,
        default="manual",
        help="Scheduled run label stored in state.json and notifications",
    )
    return parser.parse_args()


async def run_once(*, run_type: str) -> int:
    """Invoke the graph, persist state, and return a process exit code."""
    try:
        final_state = await invoke_graph(run_type=run_type)
        persist_state(final_state)
        await maybe_send_proactive_brief(final_state)
        if final_state.get("errors"):
            logger.warning("Run finished with %d non-fatal errors", len(final_state["errors"]))
        return 0
    except Exception:
        logger.exception("Fatal error during scheduled run")
        return 1


def main() -> None:
    args = _parse_args()
    exit_code = asyncio.run(run_once(run_type=args.run_type))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
