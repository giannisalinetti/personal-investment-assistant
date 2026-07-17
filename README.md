# PIA - Personal Investment Assistant

PIA is an agent-based tool implemented with LangGraph to help make decisions on **stocks**, **ETFs**, and **ETCs**.

## Quick start (web UI)

```bash
uv sync
cp .env.example .env   # configure as needed
open -a Ollama         # local LLM (default)
uv run pia-web         # http://127.0.0.1:8765 — also schedules Monitor 08:00/13:00/17:30
```

Dashboard **Refresh Monitor** runs an ad-hoc Monitor pipeline. Set `PIA_MONITOR_SCHEDULER=false` if you use launchd, K8s CronJobs, or Compose Ofelia instead.

## Documentation

| Guide | Description |
|-------|-------------|
| [docs/agent_architecture.md](docs/agent_architecture.md) | LangGraph Monitor + Advisor design |
| [docs/compose.md](docs/compose.md) | Docker / Podman Compose deploy |
| [docs/kubernetes.md](docs/kubernetes.md) | Kubernetes deploy |
| [docs/openshift.md](docs/openshift.md) | OpenShift + OpenShift AI (vLLM serving) |
| [docs/README.md](docs/README.md) | Index + **keep docs updated** rule |

Short pointers also live in [docker/README.md](docker/README.md) and [deploy/k8s/README.md](deploy/k8s/README.md). Product spec: [SPEC.md](SPEC.md).

## Watchlists

Edit separate files under `watchlists/`:

- `watchlists/stock.yaml`
- `watchlists/etf.yaml`
- `watchlists/etc.yaml`

## LLM providers

Default is **Ollama on the host**. For cloud / SOTA APIs set in `.env`:

```bash
PIA_LLM_PROVIDER=anthropic          # or openai / vllm
# or split:
PIA_LLM_MONITOR_PROVIDER=ollama
PIA_LLM_ADVISOR_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
```

vLLM / OpenAI-compatible (Compose `gpu`, Kubernetes, or OpenShift AI):

```bash
PIA_LLM_PROVIDER=vllm
OPENAI_BASE_URL=http://vllm:8000/v1   # or LLM_BASE_URL= / RHOAI route
OPENAI_MODEL=Qwen/Qwen3-8B            # or VLLM_MODEL=
OPENAI_API_KEY=not-needed
```

Inside Compose/Podman containers pointing at **host** Ollama, use:

```bash
OLLAMA_BASE_URL=http://host.containers.internal:11434
```

Cloud mode sends watchlist tickers, signals, and headlines to the provider.

## Agent skills

Runtime skills live in `.agents/skills/` ([agentskills.io](https://agentskills.io/specification)). They auto-activate by asset class and intent for Advisor, and as a lean subset for Monitor LLM polish/scoring.

## Telemetry

See [deploy/otel/README.md](deploy/otel/README.md) for Aspire Dashboard on Podman and OTLP GenAI traces.

## More

See [SPEC.md](SPEC.md) for Telegram, scheduled runs, and the full specification. Prefer [docs/](docs/) for day-to-day operator and architecture reading.
