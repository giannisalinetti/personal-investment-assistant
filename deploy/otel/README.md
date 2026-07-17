# OpenTelemetry + Aspire Dashboard

Local performance investigation uses OTLP traces with
[GenAI semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai).

## Start the dashboard (Podman)

```bash
podman compose -f deploy/otel/compose.podman.yml up -d
# Dashboard UI: http://localhost:18888
```

## Enable PIA export

In `.env`:

```bash
PIA_OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:18889
OTEL_SERVICE_NAME=pia
```

Restart `pia-web` / `pia-bot` / run `uv run pia-graph`. Spans appear for:

- `gen_ai.chat.monitor` / `gen_ai.chat.advisor` (LLM calls)
- `pia.graph.*` (Monitor nodes)
- `pia.advisor.respond` / `pia.advisor.fetch` / `pia.advisor.llm`
- `pia.skills.activated` (when skills load)

Telemetry is **off** by default (`PIA_OTEL_ENABLED=false`).
