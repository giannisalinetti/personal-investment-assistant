"""Ollama LLM factory — single instantiation point for ChatOllama."""

from __future__ import annotations

from langchain_ollama import ChatOllama

from src.config import settings


def get_llm(temperature: float = 0.1) -> ChatOllama:
    """Monitor pipeline — reasoning off, small context, short output."""
    return ChatOllama(
        model=settings.OLLAMA_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=temperature,
        reasoning=False,
        num_ctx=settings.OLLAMA_NUM_CTX,
        num_predict=settings.OLLAMA_NUM_PREDICT,
    )


def get_advisor_llm(temperature: float = 0.3) -> ChatOllama:
    """Advisor mode — optional chain-of-thought; context sized for deliberation."""
    return ChatOllama(
        model=settings.OLLAMA_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=temperature,
        reasoning=settings.OLLAMA_ADVISOR_REASONING,
        num_ctx=settings.OLLAMA_ADVISOR_NUM_CTX,
        num_predict=settings.OLLAMA_ADVISOR_NUM_PREDICT,
    )
