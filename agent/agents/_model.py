"""Shared Amazon Bedrock model factory for all agents."""

import os

from strands.models import BedrockModel

# Default to Amazon Nova Pro (cross-region inference profile): Amazon-native,
# needs no Marketplace subscription, and supports tool calling — so it runs out
# of the box. Override with BEDROCK_MODEL_ID. Switch to
# "us.anthropic.claude-sonnet-4-6" once Anthropic model access + a valid AWS
# payment method are enabled on the account.
DEFAULT_MODEL_ID = "us.amazon.nova-pro-v1:0"


def get_model(env_var: str | None = None) -> BedrockModel:
    """Build a BedrockModel from environment configuration.

    Resolution order for the model id:
      1. The per-agent override in ``env_var`` (e.g. ``SEARCH_MODEL_ID``), if set.
      2. ``BEDROCK_MODEL_ID`` (the global default for all agents).
      3. ``DEFAULT_MODEL_ID``.

    Args:
        env_var: Name of an agent-specific env var to check first. Lets each
            specialist run on a different model (e.g. a stronger tool-calling
            model for the search agent). Small models such as
            ``openai.gpt-oss-20b`` are unreliable at emitting valid tool-call
            arguments and may crash tool validation — prefer a capable model
            for agents that call tools.
    """
    model_id = (
        (os.getenv(env_var) if env_var else None)
        or os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
    )
    return BedrockModel(
        model_id=model_id,
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )
