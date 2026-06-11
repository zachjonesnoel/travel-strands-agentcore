"""Flight search tool — uses structured DuckDuckGo queries (no paid GDS API).

This simulates flight discovery by searching the web for route/fare pages.
It is not a live booking/pricing feed; results are indicative links the
flights agent summarizes for the traveler.
"""

import logging

from strands import tool

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover
    from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


@tool
def search_flights(origin: str, destination: str, departure_date: str) -> str:
    """Search for flight options between two cities on a given date.

    Args:
        origin: Departure city or airport, e.g. "New York" or "JFK".
        destination: Arrival city or airport, e.g. "Tokyo" or "HND".
        departure_date: Departure date, e.g. "2026-03-15" or "March 15 2026".

    Returns:
        A formatted list of indicative flight/fare result links and snippets.
    """
    query = (
        f"flights from {origin} to {destination} on {departure_date} "
        f"price airline schedule"
    )
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=6))
    except Exception as exc:
        logger.warning("search_flights failed (%s->%s): %s", origin, destination, exc)
        return f"Flight search temporarily unavailable: {exc}"

    if not results:
        return (
            f"No flight results found for {origin} → {destination} "
            f"on {departure_date}."
        )

    lines = [f"Indicative flight options: {origin} → {destination} on {departure_date}"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. {r.get('title', '(no title)')}\n"
            f"   {r.get('body', '')}\n   {r.get('href', '')}"
        )
    return "\n".join(lines)
