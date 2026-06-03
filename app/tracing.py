"""Optional OpenTelemetry tracing.

Fully guarded: a no-op unless ``OTEL_ENABLED`` is true *and* the OpenTelemetry
packages are installed. Instruments FastAPI, outgoing HTTP (requests) and
SQLAlchemy, exporting spans over OTLP/gRPC.
"""
import logging

from config import OTEL_ENABLED, OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME

logger = logging.getLogger("uvicorn.error")


def setup_tracing(app, engine=None) -> None:
    if not OTEL_ENABLED:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        except Exception:
            SQLAlchemyInstrumentor = None
    except Exception:
        logger.warning(
            "OTEL_ENABLED is set but opentelemetry packages are not installed; "
            "tracing disabled"
        )
        return

    provider = TracerProvider(
        resource=Resource.create({"service.name": OTEL_SERVICE_NAME})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT))
    )
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    RequestsInstrumentor().instrument()
    if SQLAlchemyInstrumentor is not None and engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine)

    logger.info(
        "OpenTelemetry tracing enabled (service=%s, endpoint=%s)",
        OTEL_SERVICE_NAME,
        OTEL_EXPORTER_OTLP_ENDPOINT,
    )
