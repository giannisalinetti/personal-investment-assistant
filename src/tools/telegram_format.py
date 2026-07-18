"""Convert Advisor / notification plain text to Telegram HTML."""

from __future__ import annotations

import html
import re

_CODE_FENCE = re.compile(r"```([\s\S]*?)```")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC_STAR = re.compile(r"(?<!\*)\*(?!\*)([^*\n]+?)(?<!\*)\*(?!\*)")
_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_BARE_URL = re.compile(r"(?<![\w\"'=])(https?://[^\s<>\[\]]+)")


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def to_telegram_html(text: str) -> str:
    """Convert markdown-ish plain text to Telegram HTML (parse_mode=HTML).

    Escapes raw HTML, then applies a conservative markdown subset:
    headings, bold, italic (*…*), inline/fenced code, markdown links, bare URLs.
    """
    body = text.strip()
    if not body:
        return ""

    placeholders: dict[str, str] = {}
    counter = 0

    def _ph(snippet: str) -> str:
        nonlocal counter
        key = f"\x00PH{counter}\x00"
        counter += 1
        placeholders[key] = snippet
        return key

    def _fence(match: re.Match[str]) -> str:
        return _ph(f"<pre>{_escape(match.group(1).strip(chr(10)))}</pre>")

    body = _CODE_FENCE.sub(_fence, body)

    def _code(match: re.Match[str]) -> str:
        return _ph(f"<code>{_escape(match.group(1))}</code>")

    body = _INLINE_CODE.sub(_code, body)

    def _md_link(match: re.Match[str]) -> str:
        label = _escape(match.group(1))
        href = html.escape(match.group(2), quote=True)
        return _ph(f'<a href="{href}">{label}</a>')

    body = _MD_LINK.sub(_md_link, body)

    def _bare(match: re.Match[str]) -> str:
        raw = match.group(1)
        url = raw.rstrip(".,);]")
        trailing = raw[len(url) :]
        href = html.escape(url, quote=True)
        return _ph(f'<a href="{href}">{_escape(url)}</a>') + trailing

    body = _BARE_URL.sub(_bare, body)

    body = _escape(body)

    lines_out: list[str] = []
    for line in body.split("\n"):
        match = _HEADING.match(line)
        if match:
            lines_out.append(f"<b>{match.group(2).strip()}</b>")
        else:
            lines_out.append(line)
    body = "\n".join(lines_out)

    def _bold(match: re.Match[str]) -> str:
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        return f"<b>{inner}</b>"

    body = _BOLD.sub(_bold, body)
    body = _ITALIC_STAR.sub(r"<i>\1</i>", body)

    for key, value in placeholders.items():
        body = body.replace(key, value)
    return body


def to_telegram_plain(text: str) -> str:
    """Escaped plain text fallback when HTML parse_mode is rejected."""
    return _escape(text.strip())
