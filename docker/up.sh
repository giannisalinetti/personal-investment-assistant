#!/usr/bin/env bash
# PIA Compose helper — picks Podman or Docker and a Compose provider.
# Usage: ./docker/up.sh [up|build|down|logs|ps|stub|gpu|help]
# Default (no args or "up"): build + start host-Ollama stack.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="docker/compose.yml"
COMPOSE_PODMAN="docker/compose.podman.yml"
COMPOSE_DOCKER="docker/compose.docker.yml"

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

Host Ollama networking (default up):
  Linux Podman — pasta maps 127.0.0.1:11434 to host loopback (Ollama stays on localhost)
  Docker       — host.docker.internal (Linux Engine: set OLLAMA_HOST=0.0.0.0:11434)
  Mac Desktop  — host gateway hostname; no pasta / no OLLAMA_HOST change
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
      echo "Created .env from .env.example — edit secrets / OLLAMA settings before first use."
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

# Extra -f overrides for host-Ollama networking (not used for gpu/stub on Podman).
# Sets COMPOSE_NET_ARGS as an array of -f flags.
compose_net_args() {
  local mode="${1:-default}"
  COMPOSE_NET_ARGS=()
  if [[ "$RUNTIME" == docker ]]; then
    COMPOSE_NET_ARGS=(-f "$COMPOSE_DOCKER")
    return
  fi
  # Podman: pasta only on Linux for default (host Ollama) path
  if [[ "$RUNTIME" == podman && "$(uname -s)" == "Linux" && "$mode" == "default" ]]; then
    COMPOSE_NET_ARGS=(-f "$COMPOSE_PODMAN")
  fi
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

EOF
  if [[ "$mode" == stub || "$mode" == "gpu / vLLM" ]]; then
    cat <<EOF
LLM is in-stack for this profile (stub or vLLM) — host Ollama is not required.

Full guide: docs/compose.md
EOF
    return
  fi

  if [[ "$RUNTIME" == podman && "$(uname -s)" == "Linux" ]]; then
    cat <<EOF
Host Ollama (Linux Podman): pasta maps container 127.0.0.1:11434 → host loopback.
  Keep Ollama on 127.0.0.1 (default). Compose sets OLLAMA_BASE_URL=http://127.0.0.1:11434
  No need for OLLAMA_HOST=0.0.0.0.

Full guide: docs/compose.md
EOF
  elif [[ "$RUNTIME" == docker ]]; then
    if [[ "$(uname -s)" == "Linux" ]]; then
      cat <<EOF
Host Ollama (Docker Engine on Linux):
  export OLLAMA_HOST=0.0.0.0:11434   # then restart Ollama
  Compose sets OLLAMA_BASE_URL=http://host.docker.internal:11434
  Firewall: bind-all exposes the LAN if port 11434 is open — restrict if needed.

Full guide: docs/compose.md
EOF
    else
      cat <<EOF
Host Ollama (Docker Desktop): OLLAMA_BASE_URL=http://host.docker.internal:11434
  Keep Ollama on the Mac host (Metal). No OLLAMA_HOST=0.0.0.0 required.

Full guide: docs/compose.md
EOF
    fi
  else
    cat <<EOF
Host Ollama (Podman Desktop / Mac): OLLAMA_BASE_URL=http://host.containers.internal:11434
  Keep Ollama on the Mac host (Metal).

Full guide: docs/compose.md
EOF
  fi
}

cmd_up() {
  ensure_env
  cmd_build
  compose_net_args default
  echo "Starting default stack (pia-web + pia-bot + one-shot pia-run) …"
  if [[ ${#COMPOSE_NET_ARGS[@]} -gt 0 ]]; then
    echo "Networking override: ${COMPOSE_NET_ARGS[*]}"
  fi
  compose -f "$COMPOSE_FILE" "${COMPOSE_NET_ARGS[@]}" up -d
  print_up_banner "default / host Ollama"
}

cmd_down() {
  ensure_env
  echo "Stopping Compose stack …"
  compose_net_args default
  # Tear down default (with net override), stub, and gpu so leftover profiles are removed.
  compose -f "$COMPOSE_FILE" "${COMPOSE_NET_ARGS[@]}" down --remove-orphans || true
  compose -f "$COMPOSE_FILE" -f docker/compose.stub.yml --profile stub down --remove-orphans 2>/dev/null || true
  compose -f "$COMPOSE_FILE" -f docker/compose.gpu.yml --profile gpu down --remove-orphans 2>/dev/null || true
  if [[ "$RUNTIME" == docker ]]; then
    compose -f "$COMPOSE_FILE" -f "$COMPOSE_DOCKER" -f docker/compose.stub.yml --profile stub down --remove-orphans 2>/dev/null || true
    compose -f "$COMPOSE_FILE" -f "$COMPOSE_DOCKER" -f docker/compose.gpu.yml --profile gpu down --remove-orphans 2>/dev/null || true
  fi
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
  compose_net_args stub
  # Podman: no pasta (need Compose network for stub DNS). Docker: still add host-gateway.
  if [[ ${#COMPOSE_NET_ARGS[@]} -gt 0 ]]; then
    compose -f "$COMPOSE_FILE" "${COMPOSE_NET_ARGS[@]}" -f docker/compose.stub.yml --profile stub up -d
  else
    compose -f "$COMPOSE_FILE" -f docker/compose.stub.yml --profile stub up -d
  fi
  print_up_banner "stub"
}

cmd_gpu() {
  ensure_env
  cmd_build
  echo "Starting GPU / vLLM stack …"
  compose_net_args gpu
  # Podman: no pasta (need Compose network for vllm). Docker: still add host-gateway.
  if [[ ${#COMPOSE_NET_ARGS[@]} -gt 0 ]]; then
    compose -f "$COMPOSE_FILE" "${COMPOSE_NET_ARGS[@]}" -f docker/compose.gpu.yml --profile gpu up -d
  else
    compose -f "$COMPOSE_FILE" -f docker/compose.gpu.yml --profile gpu up -d
  fi
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
