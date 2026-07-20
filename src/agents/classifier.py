"""Agent 2 — Classification Agent"""

from __future__ import annotations
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from src.core.state import EmailState
from src.prompts.classifier_prompt import CLASSIFIER_SYSTEM, CLASSIFIER_HUMAN
from src.core.utils import get_llm, safe_json_parse

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {
    "Work", "Personal", "Finance", "Shopping",
    "Newsletter", "Promotion", "Support", "Spam", "Unknown",
}


def classify_email(state: EmailState) -> dict:
    llm = get_llm()
    messages = [
        SystemMessage(content=CLASSIFIER_SYSTEM),
        HumanMessage(content=CLASSIFIER_HUMAN.format(
            sender=state.get("sender", ""),
            subject=state.get("subject", ""),
            body=state.get("body_text", "")[:1000],
        )),
    ]
    try:
        data = safe_json_parse(llm.invoke(messages).content)
        category = data.get("category", "Unknown")
        if category not in VALID_CATEGORIES:
            category = "Unknown"
        logger.info("Classifier: category=%s", category)
        return {"category": category, "category_reason": data.get("reason", "")}
    except Exception as exc:
        logger.error("Classification failed: %s", exc)
        return {
            "category": "Unknown",
            "category_reason": f"Classification failed: {exc}",
            "error_messages": state.get("error_messages", []) + [f"Classifier error: {exc}"],
        }
