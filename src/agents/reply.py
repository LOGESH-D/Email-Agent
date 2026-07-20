"""Agent 8 — Reply Generation Agent"""

from __future__ import annotations
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from src.core.config import REPLY_RISK_THRESHOLD, DEFAULT_REPLY_TONE
from src.core.state import EmailState
from src.prompts.reply_prompt import REPLY_SYSTEM, REPLY_HUMAN
from src.core.utils import get_llm, safe_json_parse

logger = logging.getLogger(__name__)


# Categories that should never receive an auto-reply
_NO_REPLY_CATEGORIES = {"Spam", "Newsletter", "Promotion", "Shopping"}


def generate_reply(state: EmailState) -> dict:
    risk_score = state.get("risk_score", 0)
    category   = state.get("category", "Unknown")

    if risk_score >= REPLY_RISK_THRESHOLD or category in _NO_REPLY_CATEGORIES:
        logger.info("Reply: skipped (risk=%d category=%s)", risk_score, category)
        return {"suggested_reply": "", "reply_tone": ""}

    tone = state.get("reply_tone") or DEFAULT_REPLY_TONE
    llm  = get_llm()
    messages = [
        SystemMessage(content=REPLY_SYSTEM.format(tone=tone)),
        HumanMessage(content=REPLY_HUMAN.format(
            sender=state.get("sender", ""),
            subject=state.get("subject", ""),
            body=state.get("body_text", ""),
            risk_score=risk_score,
            category=category,
            short_summary=state.get("short_summary", ""),
            action_items=", ".join(state.get("action_items", [])) or "None",
        )),
    ]
    try:
        data  = safe_json_parse(llm.invoke(messages).content)
        reply = data.get("suggested_reply", "")
        logger.info("Reply: generated %d chars", len(reply))
        return {"suggested_reply": reply, "reply_tone": tone}
    except Exception as exc:
        logger.error("Reply generation failed: %s", exc)
        return {
            "suggested_reply": "", "reply_tone": tone,
            "error_messages": state.get("error_messages", []) + [f"Reply error: {exc}"],
        }
