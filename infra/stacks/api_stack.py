"""ApiStack — the Lambda Function URL proxy to the runtime, secured with IAM.

The Function URL uses AuthType=AWS_IAM, so every request must be SigV4-signed.
The browser front-end can't hold long-lived AWS credentials, so it obtains
short-lived ones from a Cognito Identity Pool (unauthenticated identities) and
signs its requests with them. Invoke permission is granted *only* to that pool's
unauthenticated IAM role — there is no public `Principal: "*"` resource policy.
"""

import re

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
        agent_runtime_arn: str,
        deployment_id: str = "dev",
        nr_env: dict | None = None,
        layer_version: str = "44",
        **kwargs,
    ) -> None:
        super().__init__(scope, cid, **kwargs)

        # Lambda function names allow letters, digits, hyphens and underscores.
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "-", deployment_id).lower()
        function_name = f"travel-api-{safe_id}"[:64]

        # New Relic AWS Lambda layer (public account 451483290750). Bundles the
        # New Relic Python agent + the New Relic extension, which sends telemetry
        # straight to New Relic using NEW_RELIC_LICENSE_KEY (no CloudWatch
        # forwarding). The layer's wrapper handler invokes our real handler named
        # by NEW_RELIC_LAMBDA_HANDLER.
        nr_layer = _lambda.LayerVersion.from_layer_version_arn(
            self,
            "NewRelicLayer",
            f"arn:aws:lambda:{self.region}:451483290750:layer:NewRelicPython312:{layer_version}",
        )

        # New Relic layer config is assembled from ../.env in infra/app.py and
        # passed in as nr_env, so all telemetry settings live in one place.
        environment = {
            "AGENT_RUNTIME_ARN": agent_runtime_arn,
            "AGENT_QUALIFIER": "DEFAULT",
            **(nr_env or {}),
        }

        fn = _lambda.Function(
            self,
            "Proxy",
            function_name=function_name,
            runtime=_lambda.Runtime.PYTHON_3_12,
            # The New Relic layer wraps our handler; it calls the real handler
            # named by NEW_RELIC_LAMBDA_HANDLER above.
            handler="newrelic_lambda_wrapper.handler",
            code=_lambda.Code.from_asset(build_api()),
            layers=[nr_layer],
            timeout=Duration.seconds(180),
            memory_size=256,
            environment=environment,
        )
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[agent_runtime_arn, f"{agent_runtime_arn}/*"],
            )
        )

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
