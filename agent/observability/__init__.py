"""New Relic agent setup (APM + AI Monitoring) and request attribute helpers."""

from observability.telemetry import (
    record_attributes,
    setup_telemetry,
    shutdown_telemetry,
)

__all__ = ["setup_telemetry", "shutdown_telemetry", "record_attributes"]
