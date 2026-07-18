# PIA - Personal Investment Assistant

PIA is an agent-based tool implemented with LangGraph to help make decisions on **stocks**, **ETFs**, and **ETCs**.

## Requirements (home / laptop)

To **run** PIA as an always-on stack you need all of the following:

| Requirement | Notes |
|-------------|--------|
| **Podman** *or* **Docker** | Container runtime |
| **Compose provider** | `podman-compose` / `podman compose`, **or** `docker compose` / `docker-compose` |
| **Ollama on the host** | Default LLM — install from [ollama.com](https://ollama.com); keep it running on port `11434`. **Pull models yourself** (`ollama pull …`); PIA/Compose never auto-pull from `.env` |
| Repo checkout | Includes `watchlists/` and `.agents/skills/` |

Optional: Telegram bot token (`TELEGRAM_*` in `.env`) for Advisor chat. Cluster deploy uses Kubernetes or OpenShift instead — see docs below.

## Quick start — Run (Compose)

PIA talks to **Ollama on the host**. Compose does **not** start Ollama and does **not** download models — you install Ollama once, pull a model, then start PIA.

### 1. Install and start Ollama

Install from [ollama.com](https://ollama.com), then make sure the daemon is running on port `11434`.

**macOS**

```bash
# After installing the Ollama app from ollama.com:
open -a Ollama
```

**Linux**

```bash
# Install (official script — see https://ollama.com/download/linux for details)
curl -fsSL https://ollama.com/install.sh | sh

# Start / enable the service (typical systemd install)
sudo systemctl enable --now ollama
# Check it is up:
systemctl status ollama
curl -sf http://127.0.0.1:11434/api/tags >/dev/null && echo "Ollama is listening"
```

If `systemctl` is not used on your distro, run `ollama serve` in a terminal (or follow your package’s docs) so something is listening on `11434`.

### 2. Pull a model (required)

Set the same name in `.env` as `OLLAMA_MODEL`. PIA only **uses** that name; it never runs `ollama pull` for you.

```bash
# Recommended default (matches .env.example) — fits a typical ~8 GB VRAM laptop GPU
ollama pull qwen3:8b
ollama list   # confirm the model is present
```

**Model ideas for a local machine**

| Hardware | Example `OLLAMA_MODEL` | Notes |
|----------|------------------------|--------|
| Average GPU (~8 GB VRAM) | `qwen3:8b` (default) | Good balance for Monitor + Advisor |
| Average GPU (lighter) | `qwen2.5:7b` or `llama3.1:8b` | Solid fallbacks if Qwen3 misbehaves |
| Stronger GPU (~12–16 GB) | `qwen3:14b` | Better Advisor quality, slower |
| CPU only (no GPU) | `llama3.2:3b` or `qwen2.5:3b` | Usable; expect slower replies — avoid 7B+ on CPU if you can |

Then point `.env` at it, for example:

```bash
PIA_LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:8b
# CPU-only example instead:
# OLLAMA_MODEL=llama3.2:3b
```

### 3. Start PIA

```bash
cd /path/to/personal-investment-assistant
cp .env.example .env
# Edit .env: set OLLAMA_MODEL (see above) and the host URL:
#   Podman:         OLLAMA_BASE_URL=http://host.containers.internal:11434
#   Docker Desktop: OLLAMA_BASE_URL=http://host.docker.internal:11434

./docker/up.sh
# or: podman-compose -f docker/compose.yml up -d
```

Dashboard: http://127.0.0.1:8765

If Advisor fails with a model / connection error, check `ollama list` and that `OLLAMA_BASE_URL` reaches the host daemon from the container (not `http://localhost:11434` inside Compose).

Default Monitor schedule is in-process APScheduler inside `pia-web` (08:00 / 13:00 / 17:30). Set `PIA_MONITOR_SCHEDULER=false` if you use K8s CronJobs or Compose Ofelia instead.

Full Compose guide (profiles, volumes, troubleshooting): [docs/compose.md](docs/compose.md).

## Develop (uv)

For contributors and CLI tools without containers:

```bash
uv sync
cp .env.example .env   # OLLAMA_BASE_URL=http://localhost:11434 is fine on the host
open -a Ollama
ollama pull qwen3:8b   # same model as OLLAMA_MODEL — PIA does not pull it
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
