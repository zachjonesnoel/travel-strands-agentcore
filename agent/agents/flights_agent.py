"""Flights specialist: find and summarize flight options for a route/date."""

from strands import Agent

from agents._model import get_model
from tools.flights_tools import search_flights

SYSTEM_PROMPT = """You are a flights specialist. Use the flight search tool to
find options for a given origin, destination, and departure date. Parse the
results into a clear summary: likely airlines, indicative price ranges, typical
durations, and direct-vs-connecting notes where available. Always remind the
traveler that prices and availability are indicative and should be confirmed on
the airline/booking site. If inputs are missing (origin, destination, or date),
state what you need."""


def build_flights_agent() -> Agent:
    return Agent(
        model=get_model("flights"),
        system_prompt=SYSTEM_PROMPT,
        tools=[search_flights],
    )
