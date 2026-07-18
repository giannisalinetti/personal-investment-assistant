# PIA - Personal Investment Assistant

PIA is an agent-based tool implemented with LangGraph to help make decisions on **stocks**, **ETFs**, and **ETCs**.

## Requirements (home / laptop)

To **run** PIA as an always-on stack you need all of the following:

| Requirement | Notes |
|-------------|--------|
| **Podman** *or* **Docker** | Container runtime |
| **Compose provider** | `podman-compose` / `podman compose`, **or** `docker compose` / `docker-compose` |
| **Ollama on the host** | Default LLM — install from [ollama.com](https://ollama.com); keep it running on port `11434` |
| Repo checkout | Includes `watchlists/` and `.agents/skills/` |

Optional: Telegram bot token (`TELEGRAM_*` in `.env`) for Advisor chat. Cluster deploy uses Kubernetes or OpenShift instead — see docs below.

## Quick start — Run (Compose)

```bash
cd /path/to/personal-investment-assistant
cp .env.example .env
# Edit .env: for Podman set
#   OLLAMA_BASE_URL=http://host.containers.internal:11434
# For Docker Desktop set
#   OLLAMA_BASE_URL=http://host.docker.internal:11434
open -a Ollama   # macOS; on Linux start the Ollama service

./docker/up.sh
# or: podman-compose -f docker/compose.yml up -d
```

Dashboard: http://127.0.0.1:8765

Default Monitor schedule is in-process APScheduler inside `pia-web` (08:00 / 13:00 / 17:30). Set `PIA_MONITOR_SCHEDULER=false` if you use K8s CronJobs or Compose Ofelia instead.

Full Compose guide (profiles, volumes, troubleshooting): [docs/compose.md](docs/compose.md).

## Develop (uv)

For contributors and CLI tools without containers:

```bash
uv sync
cp .env.example .env   # OLLAMA_BASE_URL=http://localhost:11434 is fine on the host
open -a Ollama
uv run pia-web         # http://127.0.0.1:8765
# optional: uv run pia-bot | pia-run | pia-graph | pia-console | pia-advisor
```

## Documentation

| Guide | Description |
|-------|-------------|
| [docs/compose.md](docs/compose.md) | Docker / Podman Compose (home packaging) |
| [docs/kubernetes.md](docs/kubernetes.md) | Kubernetes deploy |
| [docs/openshift.md](docs/openshift.md) | OpenShift + OpenShift AI (vLLM serving) |
| [docs/agent_architecture.md](docs/agent_architecture.md) | LangGraph Monitor + Advisor design |
| [docs/README.md](docs/README.md) | Index + **keep docs updated** rule |

Short pointers: [docker/README.md](docker/README.md), [deploy/k8s/README.md](deploy/k8s/README.md). Product spec: [SPEC.md](SPEC.md).

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
