#!/usr/bin/env python3
"""CDK app: deploys the travel planner end to end.

  TravelAgent-<id>     → AgentCore Runtime (Strands multi-agent app)
  TravelApi-<id>       → Lambda Function URL proxy (depends on the runtime ARN)
  TravelFrontend-<id>  → S3 + CloudFront static webapp (depends on the API URL)

All New Relic and Bedrock configuration lives in the repo-root ``.env`` (see
``.env.example``) — it is loaded here at synth time and forwarded to the stacks,
so there is a single place to maintain the settings. Anything already exported
in your shell environment takes precedence over ``.env``.

``DEPLOYMENT_ID`` (from .env) namespaces the CloudFormation stack names, the
resource names (AgentCore runtime, Lambda, CloudFront, S3 bucket) and the New
Relic entity names, so multiple independent deployments can coexist in one
account without colliding.
"""

import os
from pathlib import Path

import aws_cdk as cdk
from dotenv import load_dotenv

from stacks.agent_stack import AgentStack
from stacks.api_stack import ApiStack
from stacks.frontend_stack import FrontendStack

# Repo-root .env is the single source of truth for NR/Bedrock config.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

app = cdk.App()
account = os.environ.get("CDK_DEFAULT_ACCOUNT")
env = cdk.Environment(
    account=account,
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

# --- Deployment identity (single source of truth: ../.env) ---------------
# One knob that namespaces stack names, resource names, and NR entity names so
# multiple deployments (dev / staging / a teammate's) coexist in one account.
deployment_id = (os.environ.get("DEPLOYMENT_ID") or "dev").strip()

# --- Bedrock model selection (single source of truth: ../.env) -----------
# Global default plus optional per-agent overrides; only set vars are forwarded
# to the runtime (unset ones fall back to BEDROCK_MODEL_ID in agents/_model.py).
model_env = {"BEDROCK_MODEL_ID": os.environ.get("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")}
for var in (
    "ORCHESTRATOR_MODEL_ID",
    "SEARCH_MODEL_ID",
    "WEATHER_MODEL_ID",
    "FLIGHTS_MODEL_ID",
    "HOTELS_MODEL_ID",
):
    value = os.environ.get(var, "").strip()
    if value:
        model_env[var] = value

# --- New Relic config (single source of truth: ../.env) ------------------
nr_key = os.environ.get("NEW_RELIC_LICENSE_KEY", "")
nr_account_id = os.environ.get("NEW_RELIC_ACCOUNT_ID", "")
nr_layer_version = os.environ.get("NEW_RELIC_LAYER_VERSION", "44")

# New Relic entity (APM app) names — default to travel-agent-<id> / travel-api-<id>,
# overridable in .env so you control exactly how each deployment appears in NR.
nr_runtime_app_name = os.environ.get("NEW_RELIC_RUNTIME_APP_NAME") or f"travel-agent-{deployment_id}"
nr_api_app_name = os.environ.get("NEW_RELIC_API_APP_NAME") or f"travel-api-{deployment_id}"

# Environment variables set on the AgentCore runtime (New Relic Python agent).
agent_nr_env = {
    "NEW_RELIC_APP_NAME": nr_runtime_app_name,
    "NEW_RELIC_AI_MONITORING_ENABLED": os.environ.get(
        "NEW_RELIC_AI_MONITORING_ENABLED", "true"
    ),
    "NEW_RELIC_DISTRIBUTED_TRACING_ENABLED": os.environ.get(
        "NEW_RELIC_DISTRIBUTED_TRACING_ENABLED", "true"
    ),
    "NEW_RELIC_APPLICATION_LOGGING_ENABLED": os.environ.get(
        "NEW_RELIC_APPLICATION_LOGGING_ENABLED", "true"
    ),
}
if nr_key:
    agent_nr_env["NEW_RELIC_LICENSE_KEY"] = nr_key

# Environment variables set on the API Lambda (New Relic layer + extension).
api_nr_env = {
    "NEW_RELIC_APP_NAME": nr_api_app_name,
    "NEW_RELIC_LAMBDA_HANDLER": os.environ.get(
        "NEW_RELIC_LAMBDA_HANDLER", "lambda_function.handler"
    ),
    "NEW_RELIC_DISTRIBUTED_TRACING_ENABLED": os.environ.get(
        "NEW_RELIC_DISTRIBUTED_TRACING_ENABLED", "true"
    ),
    "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS": os.environ.get(
        "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS", "true"
    ),
}
if nr_account_id:
    api_nr_env["NEW_RELIC_ACCOUNT_ID"] = nr_account_id
if nr_key:
    api_nr_env["NEW_RELIC_LICENSE_KEY"] = nr_key

agent = AgentStack(
    app, "TravelAgent",
    stack_name=f"TravelAgent-{deployment_id}",
    deployment_id=deployment_id,
    model_env=model_env, nr_env=agent_nr_env, env=env,
)
api = ApiStack(
    app, "TravelApi",
    stack_name=f"TravelApi-{deployment_id}",
    deployment_id=deployment_id,
    agent_runtime_arn=agent.runtime_arn,
    nr_env=api_nr_env, layer_version=nr_layer_version,
    env=env,
)
api.add_dependency(agent)

frontend = FrontendStack(
    app, "TravelFrontend",
    stack_name=f"TravelFrontend-{deployment_id}",
    deployment_id=deployment_id,
    account=account,
    api_url=api.function_url,
    identity_pool_id=api.identity_pool_id,
    region=env.region,
    env=env,
)
frontend.add_dependency(api)

app.synth()
