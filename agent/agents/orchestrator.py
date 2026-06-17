"""Travel orchestrator: coordinates the four specialist agents as tools.

Implements the Strands "agents as tools" pattern: each specialist agent is
exposed to the orchestrator as a ``@tool``-decorated function. The orchestrator
LLM decides which specialists to call and in what order, then synthesizes a
complete travel plan from their outputs.
"""

import logging

from strands import Agent, tool

from agents._model import get_model
from agents.search_agent import build_search_agent
from agents.weather_agent import build_weather_agent
from agents.flights_agent import build_flights_agent
from agents.hotels_agent import build_hotels_agent

logger = logging.getLogger(__name__)

ORCHESTRATOR_SYSTEM_PROMPT = """You are a travel planning orchestrator. Given a
traveler's request, build a complete, well-organized trip plan by delegating to
your specialist tools:

1. research_destination — general info, attractions, tips, entry requirements.
2. check_weather — current conditions and forecasts for the travel dates.
3. find_flights — flight options for the route and departure date.
4. find_hotels — accommodation options for the destination and date range.

Plan your approach: call the specialists you need (often all four), then
synthesize their findings into a single cohesive itinerary covering: an
overview of the destination, weather + packing guidance, recommended flights,
recommended hotels, and a suggested day-by-day outline. Always note that flight
and hotel prices/availability are indicative and must be confirmed before
booking. Be concrete and well-structured."""


# --- Lazily-built specialist singletons (one model client each) ----------
_search = None
_weather = None
_flights = None
_hotels = None


def _result_text(result) -> str:
    """Normalize a Strands AgentResult to plain text."""
    try:
        return str(result)
    except Exception:  # noqa: BLE001
        return getattr(result, "message", "") or ""


@tool
def research_destination(query: str) -> str:
    """Research general travel information for a destination via web search.

    Args:
        query: What to research, e.g. "things to do in Tokyo in March, entry
            requirements, getting around".
    """
    global _search
    if _search is None:
        _search = build_search_agent()
    logger.info("Delegating to search specialist: %s", query)
    return _result_text(_search(query))


@tool
def check_weather(query: str) -> str:
    """Get weather conditions and forecasts to inform travel advice.

    Args:
        query: The weather request, e.g. "5-day forecast for Tokyo starting
            2026-03-15 with packing advice".
    """
    global _weather
    if _weather is None:
        _weather = build_weather_agent()
    logger.info("Delegating to weather specialist: %s", query)
    return _result_text(_weather(query))


@tool
def find_flights(query: str) -> str:
    """Find and summarize flight options for a route and date.

    Args:
        query: The flight request, e.g. "flights from New York to Tokyo on
            2026-03-15".
    """
    global _flights
    if _flights is None:
        _flights = build_flights_agent()
    logger.info("Delegating to flights specialist: %s", query)
    return _result_text(_flights(query))


@tool
def find_hotels(query: str) -> str:
    """Find and summarize accommodation options for a city and date range.

    Args:
        query: The hotel request, e.g. "hotels in Tokyo from 2026-03-15 to
            2026-03-20, mid-range, central".
    """
    global _hotels
    if _hotels is None:
        _hotels = build_hotels_agent()
    logger.info("Delegating to hotels specialist: %s", query)
    return _result_text(_hotels(query))


def build_orchestrator() -> Agent:
    """Build the orchestrator agent.

    Request correlation (session/environment) is attached to the New Relic
    transaction by the entry point via ``record_attributes``, so no telemetry
    attributes are threaded through here.
    """
    return Agent(
        model=get_model("orchestrator"),
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        tools=[research_destination, check_weather, find_flights, find_hotels],
    )


def run_travel_query(prompt: str) -> str:
    """Convenience helper: build the orchestrator and run a single query."""
    orchestrator = build_orchestrator()
    return _result_text(orchestrator(prompt))
