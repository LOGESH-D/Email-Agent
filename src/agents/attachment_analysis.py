"""Agent 6 — Attachment Analysis Agent"""

from __future__ import annotations
import logging
from src.core.state import EmailState
from src.tools.file_tools import analyze_attachment

logger = logging.getLogger(__name__)


def analyze_attachments(state: EmailState) -> dict:
    attachments: list[dict] = state.get("attachments", [])
    if not attachments:
        logger.info("Attachment Analysis: no attachments")
        return {"attachment_analyses": []}

    results = []
    for att in attachments:
        analysis = analyze_attachment(att)
        results.append(analysis)
        if analysis["suspicious"]:
            logger.warning("Suspicious attachment: %s — %s",
                           analysis["filename"], ", ".join(analysis["reasons"]))

    logger.info("Attachment Analysis: total=%d suspicious=%d",
                len(results), sum(1 for r in results if r["suspicious"]))
    return {"attachment_analyses": results}
