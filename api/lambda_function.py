"""Public HTTPS proxy (Lambda Function URL) in front of the agent Lambda.

A browser front-end can't safely hold AWS credentials, and the Function URL is
IAM-authenticated. This Lambda holds the IAM permission to invoke the agent
Lambda and translates a plain JSON POST into a synchronous ``lambda:Invoke``, so
the front-end just does fetch()/curl against the Function URL.

Request  (POST):  {"prompt": "...", "session_id": "optional"}
Response (200):   {"session_id": "...", "result": "..."}

CORS (and the OPTIONS preflight) is configured declaratively on the Function URL
in the CDK ApiStack, so it is intentionally NOT handled here. The Function URL is
created with AuthType=AWS_IAM, so every request must be SigV4-signed and is
authorized against the caller's IAM identity — it is NOT publicly invokable. The
browser front-end signs its requests using short-lived, unauthenticated
credentials from a Cognito Identity Pool (see the CDK ApiStack / frontend).

Telemetry: this Lambda also carries the opentelemetry-lambda layer. The incoming
request and the downstream Invoke are auto-instrumented; we additionally inject
the active trace context into the invoke payload so the agent's spans join the
same distributed trace.
"""

import base64
import json
import os
import uuid

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
AGENT_FUNCTION_NAME = os.environ["AGENT_FUNCTION_NAME"]

_client = boto3.client("lambda", region_name=REGION)


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _otel_carrier() -> dict:
    """W3C trace context for the current span, for the agent to continue.

    Best-effort: the OTel API ships with the Lambda layer. If it's unavailable
    (e.g. local unit test without the layer) we return an empty carrier.
    """
    try:
        from opentelemetry.propagate import inject

        carrier: dict = {}
        inject(carrier)
        return carrier
    except Exception:  # noqa: BLE001 - propagation is best-effort
        return {}


def handler(event, context):
    method = (
        event.get("requestContext", {}).get("http", {}).get("method", "POST").upper()
    )
    if method != "POST":
        return _resp(405, {"error": "Use POST with a JSON body."})

    # Parse body (Function URLs base64-encode some bodies)
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return _resp(400, {"error": "Body must be valid JSON."})

    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return _resp(
            400,
            {"error": "Missing 'prompt'.", "example": {"prompt": "Plan a trip to Tokyo"}},
        )

    # Reuse a caller-supplied session id (for multi-turn continuity) or mint one.
    session_id = (data.get("session_id") or "").strip() or "frontend-" + uuid.uuid4().hex

    payload = {
        "prompt": prompt,
        "session_id": session_id,
        "_otel_context": _otel_carrier(),
    }

    try:
        r = _client.invoke(
            FunctionName=AGENT_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode(),
        )
        body = r["Payload"].read()
        # A handler error surfaces as FunctionError with the trace in the payload.
        if r.get("FunctionError"):
            return _resp(502, {"error": f"Agent function error: {body.decode('utf-8', 'replace')}"})
    except Exception as exc:  # noqa: BLE001 - surface a clean error to the client
        return _resp(502, {"error": f"Agent invocation failed: {exc}"})

    try:
        return _resp(200, json.loads(body))
    except (ValueError, TypeError):
        return _resp(200, {"session_id": session_id, "raw": body.decode("utf-8", "replace")})
