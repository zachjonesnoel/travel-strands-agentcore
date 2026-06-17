"""AgentStack — the Strands multi-agent app on Amazon Bedrock AgentCore Runtime.

Deploys the agent via the AWS::BedrockAgentCore::Runtime CloudFormation resource
using a CodeConfiguration (S3 zip + managed PYTHON_3_12 runtime), so no Docker /
ECR is involved. The code zip (source + vendored arm64 deps) is produced by
infra/build.build_agent() and uploaded as a CDK S3 asset.
"""

import re

from aws_cdk import (
    Stack,
    CfnOutput,
    Token,
    CfnResource,
    aws_iam as iam,
    aws_s3_assets as s3_assets,
)
from constructs import Construct

from build import build_agent


class AgentStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        deployment_id: str,
        model_env: dict,
        nr_env: dict,
        **kwargs,
    ) -> None:
        super().__init__(scope, cid, **kwargs)

        # AgentRuntimeName allows only letters, digits and underscores and must
        # start with a letter — sanitize the deployment id accordingly.
        safe_id = re.sub(r"[^A-Za-z0-9]", "_", deployment_id)
        runtime_name = f"travel_agent_{safe_id}"[:48]

        # Execution role assumed by the AgentCore service (mirrors the toolkit's
        # default role: logs + xray + cloudwatch + bedrock:InvokeModel*).
        role = iam.Role(
            self,
            "RuntimeRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:*"
                    },
                },
            ),
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                    "logs:DescribeLogGroups",
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                    "cloudwatch:PutMetricData",
                ],
                resources=["*"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )

        # Code artifact (source + arm64 deps) → S3.
        code = s3_assets.Asset(self, "Code", path=build_agent())
        code.grant_read(role)

        # Model selection (global BEDROCK_MODEL_ID + per-agent overrides) and
        # New Relic config are both assembled from ../.env in infra/app.py, so
        # all runtime configuration lives in one place.
        env_vars = {**model_env, **nr_env}

        runtime = CfnResource(
            self,
            "Runtime",
            type="AWS::BedrockAgentCore::Runtime",
            properties={
                "AgentRuntimeName": runtime_name,
                "RoleArn": role.role_arn,
                "NetworkConfiguration": {"NetworkMode": "PUBLIC"},
                "AgentRuntimeArtifact": {
                    "CodeConfiguration": {
                        "Code": {
                            "S3": {
                                "Bucket": code.s3_bucket_name,
                                "Prefix": code.s3_object_key,
                            }
                        },
                        "Runtime": "PYTHON_3_12",
                        "EntryPoint": ["app.py"],
                    }
                },
                "EnvironmentVariables": env_vars,
            },
        )
        # Role + its inline policy (incl. S3 read on the asset) must exist first.
        runtime.node.add_dependency(role)

        self.runtime_arn = Token.as_string(runtime.get_att("AgentRuntimeArn"))
        CfnOutput(self, "RuntimeArn", value=self.runtime_arn)
