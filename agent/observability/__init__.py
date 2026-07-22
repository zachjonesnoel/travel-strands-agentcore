"""OpenTelemetry setup for traces, metrics, and logs."""

from observability.genai_capture import install_genai_capture_gate
from observability.telemetry import setup_telemetry, shutdown_telemetry

__all__ = ["setup_telemetry", "shutdown_telemetry", "install_genai_capture_gate"]
