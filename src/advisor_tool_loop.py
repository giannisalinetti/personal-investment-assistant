"""Advisor LLM tool-calling loop (provider-agnostic via LangChain bind_tools)."""

from __future__ import annotations

import logging
from typing import Any, Sequence

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOOL_ROUNDS = 6


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif hasattr(block, "text"):
                parts.append(str(getattr(block, "text")))
        return "\n".join(p for p in parts if p).strip()
    return str(content).strip()


def invoke_with_tools(
    llm: Any,
    *,
    system: str,
    user: str,
    tools: Sequence[BaseTool],
    max_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
) -> str:
    """Run a chat model with tools until it returns a final text answer.

    Works with Anthropic, OpenAI, and tool-capable Ollama models through
    LangChain ``bind_tools``. Falls back to a plain invoke if binding fails.
    """
    tool_map = {tool.name: tool for tool in tools}
    try:
        bound = llm.bind_tools(list(tools))
    except Exception as exc:
        logger.warning("bind_tools unavailable (%s); plain Advisor invoke", exc)
        response = llm.invoke(
            [SystemMessage(content=system), HumanMessage(content=user)]
        )
        return _content_to_text(getattr(response, "content", response))

    messages: list[Any] = [
        SystemMessage(content=system),
        HumanMessage(content=user),
    ]

    for round_idx in range(max_rounds):
        response = bound.invoke(messages)
        if not isinstance(response, AIMessage):
            return _content_to_text(getattr(response, "content", response))

        messages.append(response)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            text = _content_to_text(response.content)
            if text:
                return text
            logger.warning("Advisor returned empty content after %d tool round(s)", round_idx)
            return text

        logger.info(
            "Advisor tool round %d: %s",
            round_idx + 1,
            ", ".join(tc.get("name", "?") for tc in tool_calls),
        )
        for call in tool_calls:
            name = call.get("name", "")
            call_id = call.get("id") or f"call_{round_idx}_{name}"
            args = call.get("args") or {}
            tool = tool_map.get(name)
            if tool is None:
                payload = f'{{"error": "unknown tool: {name}"}}'
            else:
                try:
                    payload = tool.invoke(args)
                except Exception as exc:
                    logger.warning("Tool %s failed: %s", name, exc)
                    payload = f'{{"error": "{exc}"}}'
            if not isinstance(payload, str):
                payload = str(payload)
            messages.append(ToolMessage(content=payload, tool_call_id=call_id))

    logger.warning("Advisor tool loop hit max_rounds=%d", max_rounds)
    last = messages[-1]
    return _content_to_text(getattr(last, "content", last))
