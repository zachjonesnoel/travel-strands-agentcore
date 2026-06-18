"""AWS Lambda entry point for the travel multi-agent app.

Runs the Strands orchestrator directly on Lambda (no AgentCore Runtime). The
public proxy Lambda (api/) invokes this function synchronously with a JSON
payload; HTTP/CORS concerns live in the proxy, so this handler only deals with
the agent contract.

OpenTelemetry is provided by the opentelemetry-lambda layer: the exec wrapper
(/opt/otel-instrument) installs the global tracer/meter/logger providers and the
in-process collector forwards OTLP to New Relic. Strands attaches its GenAI spans
to that global provider, so we do NOT configure exporters here (setup_telemetry is
a no-op under the layer — see observability/telemetry.py).

Payload shape:
    {"prompt": "Plan a trip from NYC to Tokyo in March",
     "session_id": "...",            # optional
     "_otel_context": {"traceparent": "..."}}   # optional, injected by the proxy

Response shape:
    {"session_id": "...", "result": "...markdown itinerary..."}
"""

import logging
import uuid

from dotenv import load_dotenv

# Load .env (no-op in Lambda if absent), then initialize telemetry. Under the
# OTel layer setup_telemetry() is a no-op; locally it wires in-process exporters.
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from observability import setup_telemetry  # noqa: E402

setup_telemetry("travel-agent-lambda")

from agents.orchestrator import run_travel_query  # noqa: E402

logger = logging.getLogger(__name__)


def _attach_propagated_context(event: dict):
    """Attach the OTel context the proxy injected so the agent span links to it.

    Returns a detach token (or None) — the caller detaches after the run so the
    context does not leak across warm invocations on the same container.
    """
    carrier = (event or {}).get("_otel_context")
    if not carrier:
        return None
    try:
        from opentelemetry import context as otel_context
        from opentelemetry.propagate import extract

        return otel_context.attach(extract(carrier))
    except Exception as exc:  # noqa: BLE001 - propagation is best-effort
        logger.warning("Failed to attach propagated OTel context: %s", exc)
        return None


def handler(event, context=None) -> dict:
    """Handle a single agent invocation.

    Args:
        event: The invocation payload (see module docstring).
        context: Lambda context object (unused; session id comes from the payload).

    Returns:
        A JSON-serializable dict with the session id and the itinerary.
    """
    event = event or {}
    prompt = (event.get("prompt") or "").strip()
    if not prompt:
        return {
            "error": "Missing 'prompt' in payload.",
            "example": {"prompt": "Plan a 5-day trip from NYC to Tokyo in March"},
        }

    session_id = (event.get("session_id") or "").strip() or str(uuid.uuid4())

    token = _attach_propagated_context(event)
    logger.info("Lambda agent invocation (session %s)", session_id)
    try:
        result = run_travel_query(
            prompt,
            trace_attributes={
                "session.id": session_id,
                "app.environment": "lambda",
            },
        )
        return {"session_id": session_id, "result": result}
    finally:
        if token is not None:
            try:
                from opentelemetry import context as otel_context

                otel_context.detach(token)
            except Exception:  # noqa: BLE001
                pass
