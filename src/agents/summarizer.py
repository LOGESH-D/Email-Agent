"""Agent 3 — Summary Agent"""

from __future__ import annotations
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from src.core.state import EmailState
from src.prompts.summarizer_prompt import SUMMARIZER_SYSTEM, SUMMARIZER_HUMAN
from src.core.utils import get_llm, safe_json_parse

logger = logging.getLogger(__name__)


def summarize_email(state: EmailState) -> dict:
    llm = get_llm()
    messages = [
        SystemMessage(content=SUMMARIZER_SYSTEM),
        HumanMessage(content=SUMMARIZER_HUMAN.format(
            sender=state.get("sender", ""),
            subject=state.get("subject", ""),
            body=state.get("body_text", ""),
        )),
    ]
    try:
        data = safe_json_parse(llm.invoke(messages).content)
        logger.info("Summarizer: action_items=%d", len(data.get("action_items", [])))
        return {
            "short_summary":    data.get("short_summary", ""),
            "detailed_summary": data.get("detailed_summary", ""),
            "action_items":     data.get("action_items", []),
            "deadlines":        data.get("deadlines", []),
            "meeting_requests": data.get("meeting_requests", []),
            "payment_requests": data.get("payment_requests", []),
            "important_dates":  data.get("important_dates", []),
        }
    except Exception as exc:
        logger.error("Summarizer failed: %s", exc)
        return {
            "short_summary": "Summary unavailable.", "detailed_summary": "",
            "action_items": [], "deadlines": [], "meeting_requests": [],
            "payment_requests": [], "important_dates": [],
            "error_messages": state.get("error_messages", []) + [f"Summarizer error: {exc}"],
        }
