"""Agent 5 — URL Analysis Agent"""

from __future__ import annotations
import logging
from src.core.state import EmailState
from src.tools.url_tools import analyze_url

logger = logging.getLogger(__name__)


def analyze_urls(state: EmailState) -> dict:
    urls: list[str] = state.get("urls", [])
    if not urls:
        logger.info("URL Analysis: no URLs to analyse")
        return {"url_analyses": []}

    results = []
    for url in urls:
        analysis = analyze_url(url)
        results.append(analysis)
        if analysis["suspicious"]:
            logger.warning("Suspicious URL: %s — %s", url, ", ".join(analysis["reasons"]))

    logger.info("URL Analysis: total=%d suspicious=%d",
                len(results), sum(1 for r in results if r["suspicious"]))
    return {"url_analyses": results}
