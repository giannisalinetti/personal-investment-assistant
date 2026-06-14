#!/usr/bin/env zsh
# Install pia-bot Advisor daemon via launchd (macOS).
# Default shell on macOS is zsh — run directly or: zsh deploy/install-pia-bot-macos.sh
# Validate first: uv run pia-bot

emulate -L zsh
set -euo pipefail

ROOT="${0:A:h:h}"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/pia-bot" ]]; then
  print -u2 "Missing .venv/bin/pia-bot — run 'uv sync' from $ROOT first."
  exit 1
fi

if [[ "$(uname -s)" != Darwin ]]; then
  print -u2 "This script is for macOS only. Use deploy/install-pia-bot-linux.sh on Linux."
  exit 1
fi

mkdir -p "$ROOT/logs"

label="com.personalinvestmentassistant.bot"
src="$ROOT/deploy/launchd/${label}.plist"
dest="$HOME/Library/LaunchAgents/${label}.plist"

mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|/ABS/PATH/TO/personal-investment-assistant|$ROOT|g" "$src" >"$dest"

print "Installed $dest"
print ""
print "Load (start on login):"
print "  launchctl bootstrap gui/\$(id -u) \"$dest\""
print ""
print "Unload:"
print "  launchctl bootout gui/\$(id -u)/$label"
print ""
print "Logs: $ROOT/logs/bot-stdout.log"
print ""
print "Ensure Ollama is running and .env has TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID."
print "Monitor scheduled runs (pia-run) remain separate from this Advisor daemon."
print ""
print "Mac Mini / always-on tips:"
print "  • System Settings → Energy: prevent sleep on power adapter, or run: caffeinate -dims &"
print "  • After sleep, restart if stuck: launchctl kickstart -k gui/\$(id -u)/$label"
print "  • Ollama must be running too: open -a Ollama"
print ""
print "Faster Advisor (optional .env): OLLAMA_ADVISOR_REASONING=false, OLLAMA_ADVISOR_NUM_PREDICT=1024"
