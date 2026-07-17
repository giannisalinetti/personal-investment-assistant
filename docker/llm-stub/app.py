"""Minimal OpenAI-compatible chat stub for Compose/K8s smoke tests (no GPU)."""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="PIA LLM Stub", docs_url=None, redoc_url=None)

MODEL_ID = "pia-stub"


class ChatMessage(BaseModel):
    role: str
    content: str | list | None = ""


class ChatRequest(BaseModel):
    model: str = MODEL_ID
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float | None = None
    max_tokens: int | None = None


def _reply_for(messages: list[ChatMessage]) -> str:
    """Return deterministic JSON-ish or prose so Monitor + Advisor both continue."""
    blob = " ".join(str(m.content or "") for m in messages).lower()
    # Monitor nodes often ask for JSON classifications / signals polish
    if "json" in blob or "signal" in blob or "sentiment" in blob or "discover" in blob:
        return (
            '{"sentiment":"neutral","confidence":0.5,'
            '"rationale":"stub","suggestions":[],'
            '"polished_rationale":"Stub analysis — no live model."}'
        )
    return (
        "Stub LLM reply: this is a smoke-test response from the PIA OpenAI-compatible "
        "stub. No real model was invoked."
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
def list_models() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "pia",
            }
        ],
    }


@app.post("/v1/chat/completions")
def chat_completions(body: ChatRequest) -> dict:
    content = _reply_for(body.messages)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.model or MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 8,
            "completion_tokens": 16,
            "total_tokens": 24,
        },
    }
