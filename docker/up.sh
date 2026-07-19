#!/usr/bin/env bash
# PIA Compose helper — picks Podman or Docker and a Compose provider.
# Usage: ./docker/up.sh [up|build|down|logs|ps|stub|gpu|help]
# Default (no args or "up"): build + start host-Ollama stack.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="docker/compose.yml"

die() {
  echo "error: $*" >&2
  exit 1
}

have() { command -v "$1" >/dev/null 2>&1; }

usage() {
  cat <<EOF
Usage: ./docker/up.sh <command>

Commands:
  up      Build pia:local and start the default stack (host Ollama) [default]
  build   Build localhost/pia:local only
  down    Stop and remove the Compose stack
  logs    Follow pia-web / pia-bot logs
  ps      Show Compose services
  stub    Build + start stub profile (no GPU / no Ollama)
  gpu     Build + start GPU vLLM profile
  help    Show this help

Runtime (Podman preferred, else Docker) and Compose CLI are detected automatically.
Also available via Makefile: make up | build | down | logs | stub | gpu
EOF
}

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
    # Common when installed via: uv tool install podman-compose
    if have uv && uv tool run --from podman-compose podman-compose version >/dev/null 2>&1; then
      echo "uv tool run --from podman-compose podman-compose"
      return
    fi
    if podman compose version >/dev/null 2>&1; then
      echo "podman compose"
      return
    fi
    die "need podman-compose (pip/uv tool install podman-compose) or 'podman compose'"
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

ensure_env() {
  if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
      cp .env.example .env
      echo "Created .env from .env.example — edit secrets / OLLAMA_BASE_URL before first use."
    else
      touch .env
    fi
  fi
}

# Run compose with word-splitting so "podman compose" / "docker compose" work.
compose() {
  # shellcheck disable=SC2086
  $COMPOSE_CMD "$@"
}

cmd_build() {
  echo "Building localhost/pia:local …"
  "$RUNTIME" build -t localhost/pia:local -f docker/Dockerfile .
}

cmd_build_stub_image() {
  echo "Building localhost/pia-llm-stub:local …"
  "$RUNTIME" build -t localhost/pia-llm-stub:local -f docker/llm-stub/Dockerfile docker/llm-stub
}

print_up_banner() {
  local mode="$1"
  cat <<EOF

PIA is up ($mode).
  Dashboard: http://127.0.0.1:8765

Default LLM is host Ollama unless you used stub/gpu.
  Podman:  OLLAMA_BASE_URL=http://host.containers.internal:11434
  Docker:  OLLAMA_BASE_URL=http://host.docker.internal:11434

Full guide: docs/compose.md
EOF
}

cmd_up() {
  ensure_env
  cmd_build
  echo "Starting default stack (pia-web + pia-bot + one-shot pia-run) …"
  compose -f "$COMPOSE_FILE" up -d
  print_up_banner "default / host Ollama"
}

cmd_down() {
  ensure_env
  echo "Stopping Compose stack …"
  # Tear down default, stub, and gpu project configs so leftover profiles are removed.
  compose -f "$COMPOSE_FILE" down --remove-orphans || true
  compose -f "$COMPOSE_FILE" -f docker/compose.stub.yml --profile stub down --remove-orphans 2>/dev/null || true
  compose -f "$COMPOSE_FILE" -f docker/compose.gpu.yml --profile gpu down --remove-orphans 2>/dev/null || true
  echo "Done."
}

cmd_logs() {
  ensure_env
  compose -f "$COMPOSE_FILE" logs -f pia-web pia-bot
}

cmd_ps() {
  ensure_env
  compose -f "$COMPOSE_FILE" ps
}

cmd_stub() {
  ensure_env
  cmd_build
  cmd_build_stub_image
  echo "Starting stub stack …"
  compose -f "$COMPOSE_FILE" -f docker/compose.stub.yml --profile stub up -d
  print_up_banner "stub"
}

cmd_gpu() {
  ensure_env
  cmd_build
  echo "Starting GPU / vLLM stack …"
  compose -f "$COMPOSE_FILE" -f docker/compose.gpu.yml --profile gpu up -d
  print_up_banner "gpu / vLLM"
}

CMD="${1:-up}"

if [[ "$CMD" == "help" || "$CMD" == "-h" || "$CMD" == "--help" ]]; then
  usage
  exit 0
fi

RUNTIME="$(resolve_runtime)"
# Compose is only required for stack commands (not image build).
case "$CMD" in
  up|down|logs|ps|stub|gpu)
    COMPOSE_CMD="$(resolve_compose "$RUNTIME")"
    ;;
  build)
    COMPOSE_CMD=""
    ;;
  *)
    usage >&2
    die "unknown command: $CMD"
    ;;
esac

case "$CMD" in
  up) cmd_up ;;
  build) cmd_build ;;
  down) cmd_down ;;
  logs) cmd_logs ;;
  ps) cmd_ps ;;
  stub) cmd_stub ;;
  gpu) cmd_gpu ;;
esac
