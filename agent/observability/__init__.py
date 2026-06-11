"""OpenTelemetry setup for traces, metrics, and logs."""

from observability.telemetry import setup_telemetry, shutdown_telemetry

__all__ = ["setup_telemetry", "shutdown_telemetry"]
