"""Hotel search tool — uses structured DuckDuckGo queries (no paid API).

Indicative accommodation discovery via web search, not a live inventory or
pricing feed. The hotels agent summarizes the returned links for the traveler.
"""

import logging

from strands import tool

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover
    from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


@tool
def search_hotels(city: str, checkin_date: str, checkout_date: str) -> str:
    """Search for hotel/accommodation options in a city for a date range.

    Args:
        city: Destination city, e.g. "Tokyo".
        checkin_date: Check-in date, e.g. "2026-03-15".
        checkout_date: Check-out date, e.g. "2026-03-20".

    Returns:
        A formatted list of indicative hotel result links and snippets.
    """
    query = (
        f"hotels in {city} {checkin_date} to {checkout_date} "
        f"price booking reviews"
    )
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=6))
    except Exception as exc:
        logger.warning("search_hotels failed for %r: %s", city, exc)
        return f"Hotel search temporarily unavailable: {exc}"

    if not results:
        return f"No hotel results found for {city} ({checkin_date} → {checkout_date})."

    lines = [f"Indicative hotels in {city} ({checkin_date} → {checkout_date}):"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. {r.get('title', '(no title)')}\n"
            f"   {r.get('body', '')}\n   {r.get('href', '')}"
        )
    return "\n".join(lines)
