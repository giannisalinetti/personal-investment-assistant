"""OpenTelemetry setup — GenAI-aligned spans exported via OTLP HTTP."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Span, Status, StatusCode, Tracer

from src.config import settings

logger = logging.getLogger(__name__)

_INITIALIZED = False


def setup_telemetry() -> None:
    """Configure OTLP exporter when PIA_OTEL_ENABLED is true (idempotent)."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    if not settings.PIA_OTEL_ENABLED:
        logger.debug("OpenTelemetry disabled (PIA_OTEL_ENABLED=false)")
        return

    resource = Resource.create(
        {
            "service.name": settings.OTEL_SERVICE_NAME,
            "service.namespace": "personal-investment-assistant",
        }
    )
    provider = TracerProvider(resource=resource)

    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT.rstrip("/")
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        # Aspire Dashboard typically listens on http://localhost:18889/v1/traces
        traces_endpoint = (
            endpoint if endpoint.endswith("/v1/traces") else f"{endpoint}/v1/traces"
        )
        exporter = OTLPSpanExporter(endpoint=traces_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info("OpenTelemetry OTLP exporter → %s", traces_endpoint)
    except Exception as exc:
        logger.warning("OTLP exporter setup failed (%s); using console exporter", exc)
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)


def get_tracer(name: str = "pia") -> Tracer:
    """Return a tracer (no-op provider when OTEL is disabled / unset)."""
    return trace.get_tracer(name)


@contextmanager
def start_span(name: str, *, attributes: dict | None = None) -> Iterator[Span]:
    """Start a span; records exceptions onto the span."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def set_gen_ai_attributes(
    span: Span,
    *,
    provider: str,
    model: str,
    operation: str = "chat",
) -> None:
    """Apply GenAI semantic convention attributes (gen_ai.*)."""
    span.set_attribute("gen_ai.provider.name", provider)
    span.set_attribute("gen_ai.request.model", model)
    span.set_attribute("gen_ai.operation.name", operation)
    span.set_attribute("gen_ai.system", provider)
