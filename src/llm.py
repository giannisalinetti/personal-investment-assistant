"""Ollama LLM factory — single instantiation point for ChatOllama."""

from __future__ import annotations

from langchain_ollama import ChatOllama

from src.config import settings


def get_llm(temperature: float = 0.1) -> ChatOllama:
    """Return a configured ChatOllama instance."""
    return ChatOllama(
        model=settings.OLLAMA_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=temperature,
    )
