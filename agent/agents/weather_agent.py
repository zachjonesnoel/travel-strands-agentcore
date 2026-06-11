"""Weather specialist: current conditions and forecasts for travel advice."""

from strands import Agent

from agents._model import get_model
from tools.weather_tools import get_weather, get_forecast

SYSTEM_PROMPT = """You are a travel weather specialist. Use the weather tools
to report current conditions and multi-day forecasts for destination cities.
Translate raw data into practical packing and activity advice (e.g. "pack a
light jacket and an umbrella; rain likely on day 3"). When given a trip date
range, prefer the forecast tool. Be concise and traveler-focused."""


def build_weather_agent() -> Agent:
    return Agent(
        model=get_model(),
        system_prompt=SYSTEM_PROMPT,
        tools=[get_weather, get_forecast],
    )
