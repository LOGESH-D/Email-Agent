"""
Web search tool for sender/domain reputation checks.

Uses DuckDuckGo's free search via the `duckduckgo-search` package.
Falls back gracefully when the package is not installed or the search fails.
"""

from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)


def web_search(query: str, max_results: int = 5) -> List[dict]:
    """
    Perform a DuckDuckGo text search and return a list of result dicts.

    Each result contains:
        - title  : page title
        - href   : URL
        - body   : snippet / description
    """
    try:
        try:
            from ddgs import DDGS  # type: ignore  # new package name
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore  # old package name

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return results
    except ImportError:
        logger.warning(
            "duckduckgo-search not installed. "
            "Run: pip install duckduckgo-search"
        )
        return []
    except Exception as exc:
        logger.warning("Web search failed for query '%s': %s", query, exc)
        return []


def summarize_search_results(results: List[dict]) -> str:
    """Convert a list of search results into a readable text summary."""
    if not results:
        return "No search results found."

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        href = r.get("href", "")
        body = r.get("body", "")
        lines.append(f"{i}. {title}\n   {href}\n   {body}")
    return "\n\n".join(lines)
