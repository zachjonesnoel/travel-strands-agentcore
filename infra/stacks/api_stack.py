"""ApiStack — the public Lambda Function URL proxy, secured with IAM.

The Function URL uses AuthType=AWS_IAM, so every request must be SigV4-signed.
The browser front-end can't hold long-lived AWS credentials, so it obtains
short-lived ones from a Cognito Identity Pool (unauthenticated identities) and
signs its requests with them. Invoke permission is granted *only* to that pool's
unauthenticated IAM role — there is no public ``Principal: "*"`` resource policy.

The proxy invokes the agent Lambda synchronously (``lambda:Invoke``). It also
carries the opentelemetry-lambda layer so the incoming request + the downstream
invoke are traced and joined to the agent's spans (one distributed trace).
"""

from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_cognito as cognito,
)
from constructs import Construct

from build import build_api


class ApiStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        agent_function: _lambda.IFunction,
        nr_key: str,
        nr_otlp_endpoint: str,
        otel_layer_arns: list[str],
        architecture: _lambda.Architecture,
        **kwargs,
    ) -> None:
        super().__init__(scope, cid, **kwargs)

        env_vars = {
            "AGENT_FUNCTION_NAME": agent_function.function_name,
            # --- opentelemetry-lambda layer wiring (mirrors AgentStack) --------
            "AWS_LAMBDA_EXEC_WRAPPER": "/opt/otel-instrument",
            "OPENTELEMETRY_COLLECTOR_CONFIG_URI": "/var/task/collector.yaml",
            "NEW_RELIC_OTLP_ENDPOINT": nr_otlp_endpoint,
            "OTEL_SERVICE_NAME": "travel-api-proxy",
            "OTEL_RESOURCE_ATTRIBUTES": "service.name=travel-api-proxy",
            "OTEL_PROPAGATORS": "tracecontext,baggage",
            # Bridge Python logging -> OTLP logs with level + message + trace
            # correlation (see AgentStack).
            "OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED": "true",
            "OTEL_PYTHON_LOG_CORRELATION": "true",
            # See AgentStack — avoids the requests-instrumentation timeout bug.
            "OTEL_PYTHON_DISABLED_INSTRUMENTATIONS": "requests",
        }
        if nr_key:
            env_vars["NEW_RELIC_LICENSE_KEY"] = nr_key

        fn = _lambda.Function(
            self,
            "Proxy",
            runtime=_lambda.Runtime.PYTHON_3_12,
            architecture=architecture,
            handler="lambda_function.handler",
            code=_lambda.Code.from_asset(build_api()),
            timeout=Duration.seconds(180),
            memory_size=256,
            environment=env_vars,
            layers=[
                _lambda.LayerVersion.from_layer_version_arn(
                    self, f"OtelLayer{i}", arn
                )
                for i, arn in enumerate(otel_layer_arns)
            ],
        )
        # Allow the proxy to invoke the agent Lambda (adds lambda:InvokeFunction
        # to the proxy's role, scoped to the agent function).
        agent_function.grant_invoke(fn)

        # IAM-authenticated URL — callers must SigV4-sign. AWS_IAM auth means CDK
        # creates NO public resource policy; access is authorized purely by the
        # caller's IAM identity (granted below to the Cognito unauth role only).
        url = fn.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.AWS_IAM,
            cors=_lambda.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                allowed_methods=[_lambda.HttpMethod.POST],
                # Headers the browser's SigV4-signed request carries.
                allowed_headers=[
                    "content-type",
                    "authorization",
                    "x-amz-date",
                    "x-amz-security-token",
                    "x-amz-content-sha256",
                ],
                max_age=Duration.days(1),
            ),
        )

        # Cognito Identity Pool issuing short-lived, unauthenticated credentials
        # to anonymous browser visitors.
        pool = cognito.CfnIdentityPool(
            self,
            "IdentityPool",
            allow_unauthenticated_identities=True,
        )

        # The IAM role those anonymous credentials assume. It may invoke ONLY
        # this Function URL — nothing else, no wildcards.
        unauth_role = iam.Role(
            self,
            "CognitoUnauthRole",
            assumed_by=iam.FederatedPrincipal(
                "cognito-identity.amazonaws.com",
                conditions={
                    "StringEquals": {"cognito-identity.amazonaws.com:aud": pool.ref},
                    "ForAnyValue:StringLike": {
                        "cognito-identity.amazonaws.com:amr": "unauthenticated"
                    },
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
        )
        fn.grant_invoke_url(unauth_role)

        cognito.CfnIdentityPoolRoleAttachment(
            self,
            "IdentityPoolRoles",
            identity_pool_id=pool.ref,
            roles={"unauthenticated": unauth_role.role_arn},
        )

        self.function_url = url.url
        self.identity_pool_id = pool.ref
        CfnOutput(self, "FunctionUrl", value=url.url)
        CfnOutput(self, "IdentityPoolId", value=pool.ref)
        CfnOutput(self, "Region", value=self.region)
