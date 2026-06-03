#!/usr/bin/env bash
# Install pia-bot Advisor daemon via systemd user unit (Linux).
# Run from anywhere after validating: uv run pia-bot

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/pia-bot" ]]; then
  echo "Missing .venv/bin/pia-bot — run 'uv sync' from $ROOT first." >&2
  exit 1
fi

if [[ "$(uname -s)" != Linux ]]; then
  echo "This script is for Linux only. Use deploy/install-pia-bot-macos.sh on macOS." >&2
  exit 1
fi

mkdir -p "$ROOT/logs"

unit="pia-bot.service"
src="$ROOT/deploy/systemd/$unit"
dest="$HOME/.config/systemd/user/$unit"

mkdir -p "$HOME/.config/systemd/user"
sed -e "s|/ABS/PATH/TO/personal-investment-assistant|$ROOT|g" "$src" >"$dest"

echo "Installed $dest"
echo ""
echo "Enable and start:"
echo "  systemctl --user daemon-reload"
echo "  systemctl --user enable --now pia-bot.service"
echo ""
echo "Status:"
echo "  systemctl --user status pia-bot.service"
echo ""
echo "Logs: $ROOT/logs/bot-stdout.log"
echo ""
echo "Ensure Ollama is running and .env has TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID."
echo "Monitor scheduled runs (pia-run) remain separate from this Advisor daemon."
