#!/usr/bin/env python3
"""CDK app: deploys the travel planner end to end.

  TravelAgent     → Lambda (Strands multi-agent app) + opentelemetry-lambda layer
  TravelApi       → Lambda Function URL proxy → invokes the agent Lambda
  TravelFrontend  → S3 + CloudFront static webapp (depends on the API URL)

Config via environment (read from your shell / .env at synth time):
  BEDROCK_MODEL_ID              default us.amazon.nova-pro-v1:0
  NEW_RELIC_LICENSE_KEY         optional; api-key for the collector's NR export
  NEW_RELIC_OTLP_ENDPOINT       default https://otlp.nr-data.net (EU: otlp.eu01...)
  OTEL_LAMBDA_LAYER_ARN         opentelemetry-lambda layer ARN (collector + SDK).
                                MUST match the function region + arch. Verify the
                                latest version/ARN for your region before deploy:
                                https://github.com/open-telemetry/opentelemetry-lambda/releases
  LAMBDA_ARCH                   arm64 (default) or x86_64
"""

import os

import aws_cdk as cdk
from aws_cdk import aws_lambda as _lambda

from stacks.agent_stack import AgentStack
from stacks.api_stack import ApiStack
from stacks.frontend_stack import FrontendStack

app = cdk.App()
region = os.environ.get("CDK_DEFAULT_REGION", "us-east-1")
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=region,
)

# Optional suffix to namespace stack names (e.g. STACK_SUFFIX=V2), so a new
# deployment can stand alongside an existing one without colliding on stack /
# cross-stack-export names.
suffix = os.environ.get("STACK_SUFFIX", "")

model_id = os.environ.get("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")
# Optional per-specialist model overrides. Only forward the ones actually set;
# unset vars fall back to BEDROCK_MODEL_ID at runtime (see agents/_model.py).
specialist_model_ids = {
    var: os.environ[var]
    for var in (
        "SEARCH_MODEL_ID",
        "WEATHER_MODEL_ID",
        "FLIGHTS_MODEL_ID",
        "HOTELS_MODEL_ID",
    )
    if os.environ.get(var)
}
nr_key = os.environ.get("NEW_RELIC_LICENSE_KEY", "")
nr_otlp_endpoint = os.environ.get("NEW_RELIC_OTLP_ENDPOINT", "https://otlp.nr-data.net")

# Architecture for both Lambdas + the OTel layer (they must match).
arch_name = os.environ.get("LAMBDA_ARCH", "arm64").lower()
is_x86 = arch_name in ("x86_64", "amd64")
architecture = _lambda.Architecture.X86_64 if is_x86 else _lambda.Architecture.ARM_64
# opentelemetry-lambda layer names use "amd64" / "arm64" as the arch token.
arch_token = "amd64" if is_x86 else "arm64"

# opentelemetry-lambda requires TWO layers (account 184161586896):
#   1. the Python layer — SDK + auto-instrumentation + /opt/otel-instrument wrapper
#      (published as a single arch-agnostic ARN, no arch suffix).
#   2. the Collector layer — the in-process OTel Collector extension that listens
#      on localhost:4318 and exports to New Relic per collector.yaml (arch-specific).
# Verify current release ARNs before deploying:
#   https://github.com/open-telemetry/opentelemetry-lambda/releases
otel_python_layer_arn = os.environ.get(
    "OTEL_LAMBDA_LAYER_ARN",
    f"arn:aws:lambda:{region}:184161586896:layer:opentelemetry-python-0_20_0:1",
)
otel_collector_layer_arn = os.environ.get(
    "OTEL_COLLECTOR_LAYER_ARN",
    f"arn:aws:lambda:{region}:184161586896:layer:opentelemetry-collector-{arch_token}-0_22_0:1",
)
otel_layer_arns = [otel_python_layer_arn, otel_collector_layer_arn]

agent = AgentStack(
    app, f"TravelAgent{suffix}",
    model_id=model_id,
    specialist_model_ids=specialist_model_ids,
    nr_key=nr_key,
    nr_otlp_endpoint=nr_otlp_endpoint,
    otel_layer_arns=otel_layer_arns,
    architecture=architecture,
    env=env,
)

api = ApiStack(
    app, f"TravelApi{suffix}",
    agent_function=agent.agent_function,
    nr_key=nr_key,
    nr_otlp_endpoint=nr_otlp_endpoint,
    otel_layer_arns=otel_layer_arns,
    architecture=architecture,
    env=env,
)
api.add_dependency(agent)

frontend = FrontendStack(
    app, f"TravelFrontend{suffix}",
    api_url=api.function_url,
    identity_pool_id=api.identity_pool_id,
    region=env.region,
    env=env,
)
frontend.add_dependency(api)

app.synth()
