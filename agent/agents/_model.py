"""Shared Amazon Bedrock model factory for all agents."""

import os

from strands.models import BedrockModel

# Default to Amazon Nova Pro (cross-region inference profile): Amazon-native,
# needs no Marketplace subscription, and supports tool calling — so it runs out
# of the box. Override with BEDROCK_MODEL_ID. Switch to
# "us.anthropic.claude-sonnet-4-6" once Anthropic model access + a valid AWS
# payment method are enabled on the account.
DEFAULT_MODEL_ID = "us.amazon.nova-pro-v1:0"


def get_model(model_env_var: str | None = None) -> BedrockModel:
    """Build a BedrockModel from environment configuration.

    Args:
        model_env_var: Optional name of a per-specialist env var (e.g.
            ``SEARCH_MODEL_ID``) selecting the model for that agent. When set
            but empty/unset, falls back to ``BEDROCK_MODEL_ID``, then to
            ``DEFAULT_MODEL_ID``. With no argument, the orchestrator default
            (``BEDROCK_MODEL_ID``) is used.
    """
    default = os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
    model_id = os.getenv(model_env_var, default) if model_env_var else default
    return BedrockModel(
        model_id=model_id,
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )
