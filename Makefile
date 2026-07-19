# Thin wrappers around docker/up.sh (Podman/Docker detection lives there).
# Usage: make up | build | down | logs | ps | stub | gpu | help

.PHONY: up build down logs ps stub gpu help

UP := ./docker/up.sh

help:
	@$(UP) help

up:
	@$(UP) up

build:
	@$(UP) build

down:
	@$(UP) down

logs:
	@$(UP) logs

ps:
	@$(UP) ps

stub:
	@$(UP) stub

gpu:
	@$(UP) gpu
