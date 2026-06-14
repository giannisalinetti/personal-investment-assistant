# PIA - Personal Investment Assistant

PIA is an agent-based tool implemented with LangGraph to help make decisions on stock and ETF market investments.

## Quick start (web UI)

```bash
uv sync
cp .env.example .env   # configure as needed
open -a Ollama         # local LLM
uv run pia-graph       # refresh data/state.json
uv run pia-web         # http://127.0.0.1:8765
```

See `SPEC.md` for Telegram, scheduled runs, and full architecture.