"""Initialize the New Relic Python agent (APM + AI Monitoring).

The New Relic agent auto-instruments the underlying LLM SDK calls that Strands
makes — Amazon Bedrock (via ``botocore`` ``invoke_model``/``converse``) and the
OpenAI client — so model invocations, token usage, and AI-monitoring events are
captured natively, with no OpenTelemetry plumbing.

Configuration is environment-variable only (no ``newrelic.ini``). The agent
reads ``NEW_RELIC_*`` vars; the important ones:
  * NEW_RELIC_LICENSE_KEY            (ingest/license key — required to report)
  * NEW_RELIC_APP_NAME               (APM app name; defaults to service_name)
  * NEW_RELIC_AI_MONITORING_ENABLED  (set "true" to capture LLM events)

Setup is best-effort: if no license key is configured, telemetry is skipped
with a warning rather than crashing the agent.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Module-level handle so callers can flush/shutdown on exit.
_application = None


def setup_telemetry(service_name: str) -> None:
    """Initialise and register the New Relic agent.

    Must be called once, as early as possible, before the LLM clients are
    imported/constructed so the agent's instrumentation hooks are applied.

    Args:
        service_name: Logical service name reported as the APM app name
            (unless ``NEW_RELIC_APP_NAME`` is already set in the environment).
    """
    global _application

    os.environ.setdefault("NEW_RELIC_APP_NAME", service_name)

    license_key = os.getenv("NEW_RELIC_LICENSE_KEY", "").strip()
    if not license_key:
        logger.warning(
            "NEW_RELIC_LICENSE_KEY is not set — New Relic agent disabled. "
            "Set it (and NEW_RELIC_APP_NAME) to report APM + AI Monitoring data."
        )
        return

    try:
        import newrelic.agent

        # Environment-only configuration (no config file).
        newrelic.agent.initialize()
        # Block briefly so the first transaction has a registered app to report
        # to; harmless if it times out (the agent connects in the background).
        _application = newrelic.agent.register_application(timeout=10.0)
        logger.info("New Relic agent initialized (app=%s).", os.environ["NEW_RELIC_APP_NAME"])
    except Exception as exc:  # noqa: BLE001 - telemetry must never break the app
        logger.warning("Failed to initialize New Relic agent: %s", exc)


def record_attributes(attrs: dict) -> None:
    """Attach custom attributes to the current New Relic transaction.

    Replaces the OpenTelemetry ``trace_attributes`` mechanism for correlating
    a request (e.g. session/environment) in the observability backend.
    """
    if not attrs:
        return
    try:
        import newrelic.agent

        for key, value in attrs.items():
            newrelic.agent.add_custom_attribute(key, value)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not record New Relic attributes: %s", exc)


def shutdown_telemetry() -> None:
    """Flush and shut down the New Relic agent. Call on process exit."""
    if _application is None:
        return
    try:
        import newrelic.agent

        newrelic.agent.shutdown_agent(timeout=60.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error during New Relic agent shutdown: %s", exc)
