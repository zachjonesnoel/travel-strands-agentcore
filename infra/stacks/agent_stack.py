"""AgentStack — the Strands multi-agent app on AWS Lambda.

Deploys the orchestrator as a regular arm64 Lambda function (no AgentCore, no
container). Observability is provided by the opentelemetry-lambda layer: the exec
wrapper installs OTel auto-instrumentation and an in-process collector that
forwards OTLP to New Relic (config bundled as collector.yaml). The proxy Lambda
(ApiStack) invokes this function synchronously.
"""

from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_lambda as _lambda,
    aws_iam as iam,
)
from constructs import Construct

from build import build_agent


class AgentStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        model_id: str,
        specialist_model_ids: dict[str, str] | None = None,
        nr_key: str,
        nr_otlp_endpoint: str,
        otel_layer_arns: list[str],
        architecture: _lambda.Architecture,
        **kwargs,
    ) -> None:
        super().__init__(scope, cid, **kwargs)

        env_vars = {
            "BEDROCK_MODEL_ID": model_id,
            # Per-specialist model overrides (SEARCH/WEATHER/FLIGHTS/HOTELS_MODEL_ID).
            # Only those set at synth time are forwarded; the rest fall back to
            # BEDROCK_MODEL_ID at runtime (agents/_model.py).
            **(specialist_model_ids or {}),
            # --- opentelemetry-lambda layer wiring -----------------------------
            # The exec wrapper installs the global OTel providers + SDK exporters
            # (pointed at the in-process collector) and auto-instruments the
            # handler / boto3 / httpx / logging.
            "AWS_LAMBDA_EXEC_WRAPPER": "/opt/otel-instrument",
            "OPENTELEMETRY_COLLECTOR_CONFIG_URI": "/var/task/collector.yaml",
            # New Relic export target read by collector.yaml (kept distinct from
            # OTEL_EXPORTER_OTLP_ENDPOINT, which the wrapper points at localhost).
            "NEW_RELIC_OTLP_ENDPOINT": nr_otlp_endpoint,
            "OTEL_SERVICE_NAME": "travel-agent-lambda",
            "OTEL_RESOURCE_ATTRIBUTES": "service.name=travel-agent-lambda",
            "OTEL_SEMCONV_STABILITY_OPT_IN": "gen_ai_latest_experimental",
            "OTEL_PROPAGATORS": "tracecontext,baggage",
            # Bridge Python `logging` records to OTLP logs so they reach New Relic
            # WITH a severity (log level) and the message body — without this the
            # only log records exported are the GenAI prompt/completion events,
            # which carry no level and a structured body. LOG_CORRELATION stamps
            # trace_id/span_id onto each log so logs link to their trace.
            "OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED": "true",
            "OTEL_PYTHON_LOG_CORRELATION": "true",
            # The requests auto-instrumentation wraps the OTLP exporter's own POST
            # and miscomputes a (negative) timeout from Lambda's remaining time,
            # raising ValueError. We export via httpx/botocore + the collector, so
            # disable it.
            "OTEL_PYTHON_DISABLED_INSTRUMENTATIONS": "requests",
        }
        if nr_key:
            env_vars["NEW_RELIC_LICENSE_KEY"] = nr_key

        fn = _lambda.Function(
            self,
            "Agent",
            runtime=_lambda.Runtime.PYTHON_3_12,
            architecture=architecture,
            handler="lambda_handler.handler",
            code=_lambda.Code.from_asset(build_agent()),
            timeout=Duration.seconds(180),
            memory_size=1024,
            environment=env_vars,
            layers=[
                _lambda.LayerVersion.from_layer_version_arn(
                    self, f"OtelLayer{i}", arn
                )
                for i, arn in enumerate(otel_layer_arns)
            ],
        )

        # Bedrock model invocation (Strands' BedrockModel client).
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )

        self.agent_function = fn
        CfnOutput(self, "AgentFunctionName", value=fn.function_name)
        CfnOutput(self, "AgentFunctionArn", value=fn.function_arn)
