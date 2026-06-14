"""Render Advisor plain-text replies as safe HTML."""

from __future__ import annotations

import re

import markdown
import nh3

_URL_PATTERN = re.compile(r"(?<!\]\()(?<!\()(https?://[^\s<>()\]]+)")

# Subset safe for LLM prose: headings, lists, emphasis, links, code, hr.
_ALLOWED_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "ul",
}

_ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "target"},
}


def _linkify_bare_urls(text: str) -> str:
    """Wrap bare URLs so markdown renders them as clickable links."""
    return _URL_PATTERN.sub(r"<\1>", text)


def render_advisor_markdown(text: str) -> str:
    """Convert Advisor markdown-ish text to sanitized HTML."""
    body = text.strip()
    if not body:
        return ""

    body = _linkify_bare_urls(body)
    html = markdown.markdown(
        body,
        extensions=["extra", "nl2br", "sane_lists"],
        output_format="html5",
    )
    return nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        link_rel="noopener noreferrer",
        url_schemes={"http", "https", "mailto"},
    )
