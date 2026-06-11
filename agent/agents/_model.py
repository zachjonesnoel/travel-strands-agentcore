"""Shared Amazon Bedrock model factory for all agents."""

import os

from strands.models import BedrockModel

# Default to Amazon Nova Pro (cross-region inference profile): Amazon-native,
# needs no Marketplace subscription, and supports tool calling — so it runs out
# of the box. Override with BEDROCK_MODEL_ID. Switch to
# "us.anthropic.claude-sonnet-4-6" once Anthropic model access + a valid AWS
# payment method are enabled on the account.
DEFAULT_MODEL_ID = "us.amazon.nova-pro-v1:0"


def get_model() -> BedrockModel:
    """Build a BedrockModel from environment configuration."""
    return BedrockModel(
        model_id=os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )
