"""LLM factory — Ollama (default), Anthropic, or OpenAI-compatible providers."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama

from src.config import settings
from src.telemetry import set_gen_ai_attributes, start_span

logger = logging.getLogger(__name__)


def _monitor_provider() -> str:
    return settings.resolved_monitor_provider()


def _advisor_provider() -> str:
    return settings.resolved_advisor_provider()


def _build_ollama(*, temperature: float, reasoning: bool, num_ctx: int, num_predict: int) -> ChatOllama:
    return ChatOllama(
        model=settings.OLLAMA_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=temperature,
        reasoning=reasoning,
        num_ctx=num_ctx,
        num_predict=num_predict,
    )


def _build_anthropic(*, temperature: float, max_tokens: int) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    if not settings.ANTHROPIC_API_KEY.strip():
        raise RuntimeError("ANTHROPIC_API_KEY is required for Anthropic provider")
    return ChatAnthropic(
        model=settings.ANTHROPIC_MODEL,
        api_key=settings.ANTHROPIC_API_KEY,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _build_openai(*, temperature: float, max_tokens: int) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    if not settings.OPENAI_API_KEY.strip() and not settings.OPENAI_BASE_URL.strip():
        raise RuntimeError("OPENAI_API_KEY (or OPENAI_BASE_URL for local OpenAI-compatible) is required")
    kwargs: dict[str, Any] = {
        "model": settings.OPENAI_MODEL,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if settings.OPENAI_API_KEY.strip():
        kwargs["api_key"] = settings.OPENAI_API_KEY
    if settings.OPENAI_BASE_URL.strip():
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    return ChatOpenAI(**kwargs)


def _build_provider(
    provider: str,
    *,
    temperature: float,
    reasoning: bool,
    num_ctx: int,
    num_predict: int,
) -> tuple[BaseChatModel, str, str]:
    """Return (model, provider_name, model_id)."""
    name = provider.strip().lower() or "ollama"
    if name == "ollama":
        return (
            _build_ollama(
                temperature=temperature,
                reasoning=reasoning,
                num_ctx=num_ctx,
                num_predict=num_predict,
            ),
            "ollama",
            settings.OLLAMA_MODEL,
        )
    if name == "anthropic":
        return (
            _build_anthropic(temperature=temperature, max_tokens=num_predict),
            "anthropic",
            settings.ANTHROPIC_MODEL,
        )
    if name in {"openai", "openai-compatible", "vllm"}:
        return (
            _build_openai(temperature=temperature, max_tokens=num_predict),
            "openai",
            settings.OPENAI_MODEL,
        )
    raise RuntimeError(f"Unknown LLM provider: {provider!r} (use ollama|anthropic|openai)")


def get_llm(temperature: float = 0.1) -> BaseChatModel:
    """Monitor pipeline — fast structured calls."""
    llm, provider, model = _build_provider(
        _monitor_provider(),
        temperature=temperature,
        reasoning=False,
        num_ctx=settings.OLLAMA_NUM_CTX,
        num_predict=settings.OLLAMA_NUM_PREDICT,
    )
    return _TracedChatModel(llm, provider=provider, model=model, role="monitor")


def get_advisor_llm(temperature: float = 0.3) -> BaseChatModel:
    """Advisor mode — optional chain-of-thought when using Ollama."""
    provider_name = _advisor_provider()
    reasoning = settings.OLLAMA_ADVISOR_REASONING if provider_name == "ollama" else False
    llm, provider, model = _build_provider(
        provider_name,
        temperature=temperature,
        reasoning=reasoning,
        num_ctx=settings.OLLAMA_ADVISOR_NUM_CTX,
        num_predict=settings.OLLAMA_ADVISOR_NUM_PREDICT,
    )
    return _TracedChatModel(llm, provider=provider, model=model, role="advisor")


class _TracedChatModel:
    """Thin wrapper that emits GenAI OTEL spans around invoke()."""

    def __init__(self, inner: BaseChatModel, *, provider: str, model: str, role: str) -> None:
        self._inner = inner
        self._provider = provider
        self._model = model
        self._role = role

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        with start_span(
            f"gen_ai.chat.{self._role}",
            attributes={
                "pia.llm.role": self._role,
            },
        ) as span:
            set_gen_ai_attributes(
                span,
                provider=self._provider,
                model=self._model,
                operation="chat",
            )
            return self._inner.invoke(input, config=config, **kwargs)

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_TracedChatModel":
        """Preserve OTEL wrapping after LangChain tool binding."""
        bound = self._inner.bind_tools(tools, **kwargs)
        return _TracedChatModel(
            bound,
            provider=self._provider,
            model=self._model,
            role=self._role,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
