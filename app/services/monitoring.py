import atexit
import logging
import os
import queue
from logging.handlers import QueueHandler, QueueListener

import sentry_sdk
from logtail import LogtailHandler
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import settings
from app.services.safe_logger import PIIRedactionFilter

logger = logging.getLogger("agentshield")


def setup_monitoring(app):
    """
    Sets up Sentry, Logging (Betterstack), and Tracing (OTEL/Grafana).
    """
    # 0. Sentry
    sentry_dsn = settings.model_dump().get("SENTRY_DSN")
    if sentry_dsn:
        sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=1.0)

    # 1. Logging (Betterstack)
    logtail_token = settings.LOGTAIL_SOURCE_TOKEN
    logger.setLevel(logging.INFO)

    if logtail_token:
        handler = LogtailHandler(source_token=logtail_token)
        handler.addFilter(PIIRedactionFilter())

        log_queue = queue.Queue(10000)
        queue_handler = QueueHandler(log_queue)
        listener = QueueListener(log_queue, handler)
        listener.start()
        atexit.register(listener.stop)
        logger.addHandler(queue_handler)
    else:
        console_handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 2. Observability (OTEL/Grafana)
    try:
        endpoint = settings.model_dump().get("OTEL_EXPORTER_OTLP_ENDPOINT")
        headers_str = settings.model_dump().get("OTEL_EXPORTER_OTLP_HEADERS")

        if endpoint:
            headers = dict(h.split("=") for h in headers_str.split(",")) if headers_str else {}
            service_name = settings.model_dump().get("OTEL_SERVICE_NAME", "AgentShield-Core")
            resource = Resource.create({"service.name": service_name})
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
            FastAPIInstrumentor.instrument_app(app)
            logger.info(f"✅ Observability initialized for {service_name}")
    except Exception as e:
        logger.error(f"Monitoring Init Error: {e}")
