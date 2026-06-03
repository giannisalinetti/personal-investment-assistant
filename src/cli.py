"""Shared CLI argument parsing for pia-* entry points."""

from __future__ import annotations

import argparse


def command_parser(
    prog: str,
    description: str,
    *,
    epilog: str | None = None,
) -> argparse.ArgumentParser:
    """Build an ArgumentParser with consistent formatting (--help included)."""
    return argparse.ArgumentParser(
        prog=prog,
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
