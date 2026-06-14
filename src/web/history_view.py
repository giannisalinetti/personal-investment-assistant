"""Group persisted Advisor turns into sidebar-friendly exchanges."""

from __future__ import annotations

from src.web.format import render_advisor_markdown

_PREVIEW_LEN = 72


def _preview(text: str) -> str:
    single = " ".join(text.split())
    if len(single) <= _PREVIEW_LEN:
        return single
    return f"{single[: _PREVIEW_LEN - 1]}…"


def exchanges_from_turns(turns: list[dict]) -> list[dict]:
    """Pair user/assistant turns into ordered exchanges (oldest first)."""
    exchanges: list[dict] = []
    index = 0
    while index < len(turns):
        turn = turns[index]
        if turn.get("role") != "user":
            index += 1
            continue
        user_text = str(turn.get("content", ""))
        assistant_text = ""
        if index + 1 < len(turns) and turns[index + 1].get("role") == "assistant":
            assistant_text = str(turns[index + 1].get("content", ""))
            index += 2
        else:
            index += 1
        exchange_id = len(exchanges)
        exchanges.append(
            {
                "id": exchange_id,
                "user": user_text,
                "assistant": assistant_text,
                "preview": _preview(user_text or "/brief"),
                "user_html": render_advisor_markdown(user_text),
                "assistant_html": render_advisor_markdown(assistant_text),
            }
        )
    return exchanges


def exchange_by_id(turns: list[dict], exchange_id: int) -> dict | None:
    """Return one exchange by stable index, or None."""
    exchanges = exchanges_from_turns(turns)
    for exchange in exchanges:
        if exchange["id"] == exchange_id:
            return exchange
    return None
