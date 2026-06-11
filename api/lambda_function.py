"""Public HTTPS proxy (Lambda Function URL) in front of the AgentCore runtime.

A browser front-end can't safely hold AWS credentials, and AgentCore's
InvokeAgentRuntime API requires SigV4 (IAM) auth. This Lambda holds the IAM
permission and translates a plain JSON POST into an InvokeAgentRuntime call, so
the front-end just does fetch()/curl against the Function URL.

Request  (POST):  {"prompt": "...", "session_id": "optional"}
Response (200):   {"session_id": "...", "result": "..."}

CORS (and the OPTIONS preflight) is configured declaratively on the Function URL
in the CDK ApiStack, so it is intentionally NOT handled here. The Function URL
is created with AuthType=AWS_IAM, so every request must be SigV4-signed and is
authorized against the caller's IAM identity — it is NOT publicly invokable. The
browser front-end signs its requests using short-lived, unauthenticated
credentials from a Cognito Identity Pool (see the CDK ApiStack / frontend).
"""

import base64
import json
import os
import uuid

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
QUALIFIER = os.environ.get("AGENT_QUALIFIER", "DEFAULT")

_client = boto3.client("bedrock-agentcore", region_name=REGION)


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


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

    # AgentCore requires runtimeSessionId >= 33 chars. Reuse a caller-supplied
    # one (for multi-turn continuity) or mint a fresh one.
    session_id = (data.get("session_id") or "").strip()
    if len(session_id) < 33:
        session_id = "frontend-" + uuid.uuid4().hex  # 41 chars

    try:
        r = _client.invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN,
            qualifier=QUALIFIER,
            runtimeSessionId=session_id,
            contentType="application/json",
            accept="application/json",
            payload=json.dumps({"prompt": prompt, "session_id": session_id}).encode(),
        )
        body = r["response"].read()
    except Exception as exc:  # noqa: BLE001 - surface a clean error to the client
        return _resp(502, {"error": f"Agent invocation failed: {exc}"})

    try:
        return _resp(200, json.loads(body))
    except (ValueError, TypeError):
        return _resp(200, {"session_id": session_id, "raw": body.decode("utf-8", "replace")})
