"""Shared Amazon Bedrock model factory for all agents.

Each agent can run on its own model. The model id for an agent is resolved in
priority order:

    1. ``<AGENT>_MODEL_ID``   e.g. SEARCH_MODEL_ID, ORCHESTRATOR_MODEL_ID
    2. ``BEDROCK_MODEL_ID``   global default for every agent
    3. ``DEFAULT_MODEL_ID``   hard-coded fallback (Amazon Nova Pro)

This lets you mix models from the .env — e.g. a strong orchestrator with cheaper
specialists — without any code change.
"""

import logging
import os

from strands.models import BedrockModel

logger = logging.getLogger(__name__)

# Default to Amazon Nova Pro (cross-region inference profile): Amazon-native,
# needs no Marketplace subscription, and supports tool calling — so it runs out
# of the box. Override globally with BEDROCK_MODEL_ID, or per-agent with
# <AGENT>_MODEL_ID (e.g. ORCHESTRATOR_MODEL_ID=us.anthropic.claude-sonnet-4-6).
DEFAULT_MODEL_ID = "us.amazon.nova-pro-v1:0"


def _resolve_model_id(agent: str | None) -> str:
    """Pick the model id for ``agent`` using the priority order above."""
    if agent:
        per_agent = os.getenv(f"{agent.upper()}_MODEL_ID", "").strip()
        if per_agent:
            return per_agent
    return os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)


def get_model(agent: str | None = None) -> BedrockModel:
    """Build a BedrockModel for a given agent from environment configuration.

    Args:
        agent: Logical agent name (e.g. "orchestrator", "search"). When set, an
            ``<AGENT>_MODEL_ID`` env var overrides the global ``BEDROCK_MODEL_ID``.
    """
    model_id = _resolve_model_id(agent)
    logger.info("Model for %s: %s", agent or "default", model_id)
    return BedrockModel(
        model_id=model_id,
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )
