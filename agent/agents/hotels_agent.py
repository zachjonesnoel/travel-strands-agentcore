"""Hotels specialist: find and summarize accommodation options."""

from strands import Agent

from agents._model import get_model
from tools.hotels_tools import search_hotels

SYSTEM_PROMPT = """You are an accommodation specialist. Use the hotel search
tool to find lodging options in a destination city for the given check-in and
check-out dates. Summarize results into a useful shortlist: neighborhood,
apparent price tier, and what each option is known for (location, value,
luxury, family-friendly). Always note that prices and availability are
indicative and should be confirmed on the booking site. If dates or city are
missing, state what you need."""


def build_hotels_agent() -> Agent:
    return Agent(
        model=get_model("hotels"),
        system_prompt=SYSTEM_PROMPT,
        tools=[search_hotels],
    )
