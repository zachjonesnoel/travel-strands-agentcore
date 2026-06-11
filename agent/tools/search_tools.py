"""General web search tool backed by DuckDuckGo (no API key required)."""

import logging

from strands import tool

# The package was renamed `duckduckgo-search` -> `ddgs`. Support both.
try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover - fallback for older installs
    from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


@tool
def duckduckgo_search(query: str, max_results: int = 5) -> str:
    """Search the web for general information using DuckDuckGo.

    Use this for destination overviews, attractions, visa/entry notes,
    local tips, events, and anything not covered by the weather, flights,
    or hotels tools.

    Args:
        query: The search query, e.g. "top attractions in Tokyo in March".
        max_results: Maximum number of results to return (1-10).

    Returns:
        A formatted list of result titles, snippets, and URLs, or a
        message indicating no results were found.
    """
    max_results = max(1, min(int(max_results), 10))
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as exc:  # network/rate-limit resilience
        logger.warning("duckduckgo_search failed for %r: %s", query, exc)
        return f"Search temporarily unavailable for '{query}': {exc}"

    if not results:
        return f"No results found for '{query}'."

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        body = r.get("body", "")
        href = r.get("href", "")
        lines.append(f"{i}. {title}\n   {body}\n   {href}")
    return "\n".join(lines)
