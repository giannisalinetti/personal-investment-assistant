# PIA containers (Docker Compose / Podman Compose)

**Full guide:** [docs/compose.md](../docs/compose.md)

Architecture: [docs/agent_architecture.md](../docs/agent_architecture.md). Kubernetes: [docs/kubernetes.md](../docs/kubernetes.md). OpenShift AI: [docs/openshift.md](../docs/openshift.md).

## Quick start — stub (no GPU)

Requires a Compose provider: Docker Compose v2 plugin, or `pip install podman-compose`.

```bash
cd /path/to/personal-investment-assistant

podman build -t localhost/pia:local -f docker/Dockerfile .
podman build -t localhost/pia-llm-stub:local -f docker/llm-stub/Dockerfile docker/llm-stub

podman-compose -f docker/compose.yml -f docker/compose.stub.yml --profile stub up -d

curl -s http://127.0.0.1:8765/api/health
podman-compose -f docker/compose.yml -f docker/compose.stub.yml --profile stub run --rm pia-run --run-type manual
```

Dashboard: http://127.0.0.1:8765

## Profiles (summary)

| Profile / override | Purpose |
|--------------------|---------|
| (default) | `pia-web` + `pia-bot` + one-shot `pia-run` — host Ollama or cloud via `.env` |
| `--profile stub` + `compose.stub.yml` | OpenAI-compatible stub |
| `--profile gpu` + `compose.gpu.yml` | Real vLLM on NVIDIA |
| `--profile schedule` + `compose.schedule.yml` | Ofelia (set `PIA_MONITOR_SCHEDULER=false`) |

Default Monitor schedule is **in-process** APScheduler (`PIA_MONITOR_SCHEDULER=true`). See [docs/compose.md](../docs/compose.md) for env matrix, volumes, and troubleshooting.
