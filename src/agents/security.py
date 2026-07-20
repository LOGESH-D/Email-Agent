"""Agent 4 — Security Analysis Agent"""

from __future__ import annotations
import json, logging
from langchain_core.messages import HumanMessage, SystemMessage
from src.core.state import EmailState
from src.prompts.security_prompt import SECURITY_SYSTEM, SECURITY_HUMAN
from src.core.utils import get_llm, safe_json_parse

logger = logging.getLogger(__name__)
VALID_SEVERITIES = {"Low", "Medium", "High", "Critical"}


def analyze_security(state: EmailState) -> dict:
    llm = get_llm()
    messages = [
        SystemMessage(content=SECURITY_SYSTEM),
        HumanMessage(content=SECURITY_HUMAN.format(
            sender=state.get("sender", ""),
            sender_domain=state.get("sender_domain", ""),
            subject=state.get("subject", ""),
            body=state.get("body_text", ""),
            urls=", ".join(state.get("urls", [])) or "None",
            attachments=", ".join(a.get("filename", "?") for a in state.get("attachments", [])) or "None",
            headers=json.dumps(state.get("headers", {}), indent=2),
        )),
    ]
    try:
        data = safe_json_parse(llm.invoke(messages).content)
        risk_score = max(0, min(100, int(data.get("risk_score", 0))))
        severity   = data.get("severity", "Low")
        if severity not in VALID_SEVERITIES:
            severity = "Low"
        logger.info("Security: risk=%d severity=%s findings=%d",
                    risk_score, severity, len(data.get("findings", [])))
        return {
            "security_findings":    data.get("findings", []),
            "risk_score":           risk_score,
            "severity":             severity,
            "security_explanation": data.get("explanation", ""),
        }
    except Exception as exc:
        logger.error("Security analysis failed: %s", exc)
        return {
            "security_findings": [], "risk_score": 0, "severity": "Low",
            "security_explanation": f"Security analysis failed: {exc}",
            "error_messages": state.get("error_messages", []) + [f"Security error: {exc}"],
        }
