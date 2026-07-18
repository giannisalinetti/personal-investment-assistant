# PIA containers (Docker Compose / Podman Compose)

**Home packaging** for PIA. Full guide: [docs/compose.md](../docs/compose.md).

Architecture: [docs/agent_architecture.md](../docs/agent_architecture.md). Kubernetes: [docs/kubernetes.md](../docs/kubernetes.md). OpenShift AI: [docs/openshift.md](../docs/openshift.md).

## Prerequisites

| Requirement | Install / check |
|-------------|-----------------|
| **Podman** *or* **Docker** | `podman --version` or `docker --version` |
| **Compose provider** | `podman-compose` / `podman compose`, **or** `docker compose` / `docker-compose` |
| **Ollama on the host** (default LLM) | [ollama.com](https://ollama.com) — must listen on host port `11434` |
| `.env` at repo root | `cp .env.example .env` then set container host gateway URL (below) |

Stub / GPU / cloud profiles are optional overrides — see [docs/compose.md](../docs/compose.md).

## Quick start — host Ollama (default)

```bash
cd /path/to/personal-investment-assistant
cp .env.example .env
# Podman:
#   OLLAMA_BASE_URL=http://host.containers.internal:11434
# Docker Desktop:
#   OLLAMA_BASE_URL=http://host.docker.internal:11434

./docker/up.sh
```

Dashboard: http://127.0.0.1:8765

Equivalent manual commands:

```bash
podman build -t localhost/pia:local -f docker/Dockerfile .
podman-compose -f docker/compose.yml up -d
```

## Quick start — stub (no GPU, no Ollama)

```bash
podman build -t localhost/pia:local -f docker/Dockerfile .
podman build -t localhost/pia-llm-stub:local -f docker/llm-stub/Dockerfile docker/llm-stub

podman-compose -f docker/compose.yml -f docker/compose.stub.yml --profile stub up -d

curl -s http://127.0.0.1:8765/api/health
podman-compose -f docker/compose.yml -f docker/compose.stub.yml --profile stub run --rm pia-run --run-type manual
```

## Profiles (summary)

| Profile / override | Purpose |
|--------------------|---------|
| (default) | `pia-web` + `pia-bot` + one-shot `pia-run` — **host Ollama** or cloud via `.env` |
| `--profile stub` + `compose.stub.yml` | OpenAI-compatible stub |
| `--profile gpu` + `compose.gpu.yml` | Real vLLM on NVIDIA |
| `--profile schedule` + `compose.schedule.yml` | Ofelia (set `PIA_MONITOR_SCHEDULER=false`) |

Default Monitor schedule is **in-process** APScheduler (`PIA_MONITOR_SCHEDULER=true`). See [docs/compose.md](../docs/compose.md) for env matrix, volumes, and troubleshooting.
