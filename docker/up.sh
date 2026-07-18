#!/usr/bin/env bash
# Start the default PIA Compose stack (host Ollama — no stub/gpu profiles).
# Prerequisites: Podman or Docker, a Compose provider, and Ollama on the host.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

die() {
  echo "error: $*" >&2
  exit 1
}

have() { command -v "$1" >/dev/null 2>&1; }

resolve_runtime() {
  if have podman; then
    echo podman
  elif have docker; then
    echo docker
  else
    die "need Podman or Docker installed and on PATH"
  fi
}

resolve_compose() {
  local runtime="$1"
  if [[ "$runtime" == podman ]]; then
    if have podman-compose; then
      echo "podman-compose"
      return
    fi
    if podman compose version >/dev/null 2>&1; then
      echo "podman compose"
      return
    fi
    die "need podman-compose (pip install podman-compose) or 'podman compose'"
  fi
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
    return
  fi
  if have docker-compose; then
    echo "docker-compose"
    return
  fi
  die "need Docker Compose v2 ('docker compose') or docker-compose"
}

RUNTIME="$(resolve_runtime)"
COMPOSE_CMD="$(resolve_compose "$RUNTIME")"

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "Created .env from .env.example — edit secrets / OLLAMA_BASE_URL before first use."
  else
    touch .env
  fi
fi

echo "Building localhost/pia:local …"
"$RUNTIME" build -t localhost/pia:local -f docker/Dockerfile .

echo "Starting default stack (pia-web + pia-bot + one-shot pia-run) …"
# shellcheck disable=SC2086
$COMPOSE_CMD -f docker/compose.yml up -d

cat <<EOF

PIA is up.
  Dashboard: http://127.0.0.1:8765

Default LLM is host Ollama. In .env for containers use:
  Podman:  OLLAMA_BASE_URL=http://host.containers.internal:11434
  Docker:  OLLAMA_BASE_URL=http://host.docker.internal:11434

Full guide: docs/compose.md
EOF
