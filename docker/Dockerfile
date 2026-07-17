# PIA CPU image — multi-stage uv build, non-root runtime
# Editable install keeps src/ at /app so PROJECT_ROOT (watchlists, data, skills) is correct.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY watchlists ./watchlists
COPY .agents ./.agents

RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm AS runtime

RUN useradd --create-home --uid 1000 pia \
    && mkdir -p /app/data /app/logs /app/.cache /app/data/advisor \
    && chown -R pia:pia /app

WORKDIR /app

COPY --from=builder --chown=pia:pia /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIA_WEB_HOST=0.0.0.0 \
    PIA_WEB_PORT=8765

USER pia
EXPOSE 8765

CMD ["pia-web"]
