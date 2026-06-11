"""Amazon Bedrock AgentCore Runtime entry point.

Wraps the travel orchestrator in a ``BedrockAgentCoreApp``. The runtime serves
the AgentCore contract (POST /invocations, GET /ping) on port 8080. Telemetry
is initialized at module load so spans/metrics/logs flow from the first request.

Payload shape:
    {"prompt": "Plan a trip from NYC to Tokyo in March", "session_id": "..."}
"""

import logging
import uuid

from dotenv import load_dotenv

# Load .env first (no-op in the container if absent), then telemetry, then
# import the agent so the model client is built after OTel is configured.
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from observability import setup_telemetry  # noqa: E402

setup_telemetry("travel-agent-agentcore")

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # noqa: E402

from agents.orchestrator import run_travel_query  # noqa: E402

logger = logging.getLogger(__name__)
app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    """Handle a single AgentCore invocation.

    Args:
        payload: The request body. Expects a ``prompt`` field.
        context: AgentCore runtime context (provides session metadata).

    Returns:
        A structured JSON-serializable response.
    """
    prompt = (payload or {}).get("prompt", "").strip()
    if not prompt:
        return {
            "error": "Missing 'prompt' in payload.",
            "example": {"prompt": "Plan a 5-day trip from NYC to Tokyo in March"},
        }

    session_id = (payload or {}).get("session_id") or getattr(
        context, "session_id", None
    ) or str(uuid.uuid4())

    logger.info("AgentCore invocation (session %s)", session_id)
    result = run_travel_query(
        prompt,
        trace_attributes={
            "session.id": session_id,
            "app.environment": "agentcore",
        },
    )
    return {"session_id": session_id, "result": result}


if __name__ == "__main__":
    # Serves POST /invocations and GET /ping on 0.0.0.0:8080.
    app.run()
