#!/usr/bin/env python3
"""CDK app: deploys the travel planner end to end.

  TravelAgent     → AgentCore Runtime (Strands multi-agent app)
  TravelApi       → Lambda Function URL proxy (depends on the runtime ARN)
  TravelFrontend  → S3 + CloudFront static webapp (depends on the API URL)

Config via environment (read from your shell / .env at synth time):
  BEDROCK_MODEL_ID              default us.amazon.nova-pro-v1:0
  NEW_RELIC_LICENSE_KEY         optional; enables OTel export to New Relic
  OTEL_EXPORTER_OTLP_ENDPOINT   default https://otlp.nr-data.net
"""

import os

import aws_cdk as cdk

from stacks.agent_stack import AgentStack
from stacks.api_stack import ApiStack
from stacks.frontend_stack import FrontendStack

app = cdk.App()
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

model_id = os.environ.get("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")
nr_key = os.environ.get("NEW_RELIC_LICENSE_KEY", "")
otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otlp.nr-data.net")

agent = AgentStack(
    app, "TravelAgent",
    model_id=model_id, nr_key=nr_key, otel_endpoint=otel_endpoint, env=env,
)
api = ApiStack(app, "TravelApi", agent_runtime_arn=agent.runtime_arn, env=env)
api.add_dependency(agent)

frontend = FrontendStack(
    app, "TravelFrontend",
    api_url=api.function_url,
    identity_pool_id=api.identity_pool_id,
    region=env.region,
    env=env,
)
frontend.add_dependency(api)

app.synth()
