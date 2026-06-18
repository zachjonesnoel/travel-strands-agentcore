"""Configure OpenTelemetry (traces, metrics, logs) — dual-mode.

This app runs in two environments:

* **On AWS Lambda** (production): the ``opentelemetry-lambda`` layer owns
  telemetry. Its exec wrapper (``/opt/otel-instrument``) installs the global
  tracer/meter/logger providers and OTLP exporters pointed at the in-process
  collector, which forwards to New Relic. Strands attaches its GenAI spans to
  that global provider automatically, so ``setup_telemetry`` is a **no-op** here
  — configuring our own providers would shadow the layer's and break export.

* **Local dev** (``main.py``): there is no layer, so we wire in-process OTLP/HTTP
  exporters straight to New Relic via Strands' ``StrandsTelemetry`` and bridge
  stdlib ``logging`` records to OTLP logs.

All exporters are best-effort: if no ingest key is configured, telemetry is
skipped with a warning rather than crashing the agent.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Module-level handles so callers can flush/shutdown on exit.
_tracer_provider = None
_meter_provider = None
_logger_provider = None


def _running_under_lambda_layer() -> bool:
    """True when the opentelemetry-lambda layer is managing telemetry.

    ``AWS_LAMBDA_FUNCTION_NAME`` is set by the Lambda runtime; the exec wrapper
    additionally sets ``AWS_LAMBDA_EXEC_WRAPPER``. Either means the layer owns
    the global providers and we must not install our own.
    """
    return bool(
        os.getenv("AWS_LAMBDA_FUNCTION_NAME") or os.getenv("AWS_LAMBDA_EXEC_WRAPPER")
    )


def _otlp_headers(license_key: str) -> str:
    """New Relic authenticates OTLP ingest via the ``api-key`` header."""
    return f"api-key={license_key}"


def setup_telemetry(service_name: str) -> None:
    """Initialise OTel trace, metric, and log pipelines (local dev only).

    Under the Lambda layer this returns immediately. Locally it reads:
      * NEW_RELIC_LICENSE_KEY          (ingest/license key)
      * OTEL_EXPORTER_OTLP_ENDPOINT    (defaults to https://otlp.nr-data.net)

    Args:
        service_name: Logical service name reported as ``service.name``.
    """
    global _tracer_provider, _meter_provider, _logger_provider

    if _running_under_lambda_layer():
        logger.info(
            "OpenTelemetry is managed by the Lambda layer — skipping in-process "
            "exporter setup (Strands uses the layer's global provider)."
        )
        return

    license_key = os.getenv("NEW_RELIC_LICENSE_KEY", "").strip()
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otlp.nr-data.net").strip()

    if not license_key:
        logger.warning(
            "NEW_RELIC_LICENSE_KEY is not set — telemetry exporters disabled. "
            "Set it (and OTEL_EXPORTER_OTLP_ENDPOINT) to ship spans/metrics/logs."
        )
        return

    # --- Standard OTEL_* env vars consumed by the SDK + Strands ----------
    os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
    os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = _otlp_headers(license_key)
    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
    os.environ.setdefault(
        "OTEL_RESOURCE_ATTRIBUTES", f"service.name={service_name}"
    )
    # New Relic prefers delta temporality for OTLP metrics.
    os.environ.setdefault(
        "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE", "delta"
    )
    # Best coverage for GenAI semantic conventions + log auto-instrumentation.
    os.environ.setdefault(
        "OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental"
    )
    os.environ.setdefault(
        "OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED", "true"
    )

    # --- Traces + metrics via Strands' built-in OTel integration ---------
    try:
        from strands.telemetry import StrandsTelemetry

        strands_telemetry = StrandsTelemetry()
        strands_telemetry.setup_otlp_exporter()                 # traces
        strands_telemetry.setup_meter(enable_otlp_exporter=True)  # metrics

        from opentelemetry import trace, metrics

        _tracer_provider = trace.get_tracer_provider()
        _meter_provider = metrics.get_meter_provider()
        logger.info("Strands OTel trace + metric exporters configured.")
    except Exception as exc:  # noqa: BLE001 - telemetry must never break the app
        logger.warning("Failed to configure Strands telemetry: %s", exc)

    # --- Log bridging: Python logging -> OTLP logs -----------------------
    try:
        _logger_provider = _setup_log_bridge(service_name, endpoint, license_key)
        logger.info("OTLP log exporter configured.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to configure OTLP log exporter: %s", exc)


def _setup_log_bridge(service_name: str, endpoint: str, license_key: str):
    """Route stdlib logging records to OTLP logs (New Relic Logs)."""
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create({"service.name": service_name})
    provider = LoggerProvider(resource=resource)
    set_logger_provider(provider)

    exporter = OTLPLogExporter(
        endpoint=f"{endpoint.rstrip('/')}/v1/logs",
        headers={"api-key": license_key},
    )
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

    # Attach to the root logger so all app logs are forwarded.
    handler = LoggingHandler(level=logging.INFO, logger_provider=provider)
    logging.getLogger().addHandler(handler)
    return provider


def shutdown_telemetry() -> None:
    """Flush and shut down all providers. Call on process exit."""
    for provider in (_tracer_provider, _meter_provider, _logger_provider):
        if provider is None:
            continue
        try:
            # force_flush exists on SDK providers; shutdown drains exporters.
            if hasattr(provider, "force_flush"):
                provider.force_flush()
            if hasattr(provider, "shutdown"):
                provider.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error during telemetry shutdown: %s", exc)
