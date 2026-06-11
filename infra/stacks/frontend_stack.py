"""FrontendStack — static webapp on S3, served over HTTPS via CloudFront.

The bucket stays private (CloudFront Origin Access Control). The webapp's API
URL is injected at deploy time as /config.json (no rebuild needed).
"""

from pathlib import Path

from aws_cdk import (
    Stack,
    RemovalPolicy,
    CfnOutput,
    aws_s3 as s3,
    aws_cloudfront as cf,
    aws_cloudfront_origins as origins,
    aws_s3_deployment as s3deploy,
)
from constructs import Construct

FRONTEND_DIR = str(Path(__file__).resolve().parents[2] / "frontend")


class FrontendStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        api_url: str,
        identity_pool_id: str,
        region: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, cid, **kwargs)

        bucket = s3.Bucket(
            self,
            "SiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        distribution = cf.Distribution(
            self,
            "Dist",
            default_root_object="index.html",
            default_behavior=cf.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cf.CachePolicy.CACHING_OPTIMIZED,
            ),
            comment="Wander travel-planner frontend",
        )

        s3deploy.BucketDeployment(
            self,
            "DeploySite",
            destination_bucket=bucket,
            distribution=distribution,
            distribution_paths=["/*"],
            sources=[
                s3deploy.Source.asset(FRONTEND_DIR),
                # Inject the API URL + Cognito auth config at deploy time
                # (resolves the cross-stack tokens).
                s3deploy.Source.json_data(
                    "config.json",
                    {
                        "apiUrl": api_url,
                        "identityPoolId": identity_pool_id,
                        "region": region,
                    },
                ),
            ],
        )

        CfnOutput(self, "SiteURL", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "BucketName", value=bucket.bucket_name)
