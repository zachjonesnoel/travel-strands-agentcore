"""Search specialist: general web research for travel planning."""

from strands import Agent

from agents._model import get_model
from tools.search_tools import duckduckgo_search

SYSTEM_PROMPT = """You are a travel research specialist. Use the web search
tool to find accurate, current information about destinations: top attractions,
neighborhoods, local customs, transit, safety, visa/entry requirements, and
seasonal events. Summarize findings concisely with concrete, actionable detail.
Cite source URLs where helpful. If a search returns nothing useful, say so
plainly rather than guessing."""


def build_search_agent() -> Agent:
    return Agent(
        model=get_model("SEARCH_MODEL_ID"),
        system_prompt=SYSTEM_PROMPT,
        tools=[duckduckgo_search],
    )
