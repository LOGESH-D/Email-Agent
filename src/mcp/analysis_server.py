"""
mcp/analysis_server.py — Self-contained MCP server exposing specialist analysis tools.

Provides tools for classification, summarization, security analysis, URL analysis,
attachment analysis, web/reputation search, and reply drafting.
All tools fetch the email data from the trace email cache by message_id.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from fastmcp import FastMCP  # type: ignore

from langchain_core.messages import SystemMessage, HumanMessage

from src.core.config import (
    WEB_SEARCH_MAX_RESULTS,
    DEFAULT_REPLY_TONE,
    REPLY_RISK_THRESHOLD,
)
from src.core.utils import get_llm, safe_json_parse
from src.prompts.classifier_prompt import CLASSIFIER_SYSTEM, CLASSIFIER_HUMAN
from src.prompts.summarizer_prompt import SUMMARIZER_SYSTEM, SUMMARIZER_HUMAN
from src.prompts.security_prompt import SECURITY_SYSTEM, SECURITY_HUMAN
from src.prompts.reply_prompt import REPLY_SYSTEM, REPLY_HUMAN
from src.tools.url_tools import analyze_url
from src.tools.file_tools import analyze_attachment
from src.tools.search import web_search, summarize_search_results
from src.agent.trace import get_session_email, get_trace

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="analysis-server",
    instructions=(
        "Specialist analysis tools for the Mail Analyzer Agent. "
        "Provides tools to classify, summarize, analyze security, "
        "check URLs, inspect attachments, search domain reputation, "
        "and draft email replies. All tools require the 'message_id' parameter."
    ),
)

VALID_CATEGORIES = {
    "Work",
    "Personal",
    "Finance",
    "Shopping",
    "Newsletter",
    "Promotion",
    "Support",
    "Spam",
    "Unknown",
}

_NO_REPLY_CATEGORIES = {"Spam", "Newsletter", "Promotion", "Shopping"}


@mcp.tool(
    description="Classifies the email into a primary category (Work, Personal, Finance, "
                "Shopping, Newsletter, Promotion, Support, Spam, or Unknown) and "
                "provides a brief reasoning. This tool MUST be run early."
)
def classify_email(message_id: str = "") -> dict[str, Any]:
    """
    Classify an email's content and category using the message_id.

    Args:
        message_id: The Gmail message ID (session key) of the email.
    """
    email_data = get_session_email(message_id)
    if not email_data:
        logger.error("classify_email: email not found in session cache for message_id=%s", message_id)
        return {"category": "Unknown", "category_reason": "Email not found in session cache"}

    sender = email_data.get("sender", "")
    subject = email_data.get("subject", "")
    body_text = email_data.get("body_text", "")

    llm = get_llm()
    messages = [
        SystemMessage(content=CLASSIFIER_SYSTEM),
        HumanMessage(
            content=CLASSIFIER_HUMAN.format(
                sender=sender,
                subject=subject,
                body=body_text[:1000],
            )
        ),
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
        return {"category": "Unknown", "category_reason": f"Classification failed: {exc}"}


@mcp.tool(
    description="Generates a short summary, a detailed summary, list of action items, "
                "deadlines, meeting requests, payment requests, and important dates from the email."
)
def summarize_email(message_id: str = "") -> dict[str, Any]:
    """
    Summarize the email and extract key dates, meetings, action items using the message_id.

    Args:
        message_id: The Gmail message ID (session key) of the email.
    """
    email_data = get_session_email(message_id)
    if not email_data:
        logger.error("summarize_email: email not found in session cache for message_id=%s", message_id)
        return {"short_summary": "Email not found in session cache", "action_items": []}

    sender = email_data.get("sender", "")
    subject = email_data.get("subject", "")
    body_text = email_data.get("body_text", "")

    llm = get_llm()
    messages = [
        SystemMessage(content=SUMMARIZER_SYSTEM),
        HumanMessage(
            content=SUMMARIZER_HUMAN.format(
                sender=sender,
                subject=subject,
                body=body_text,
            )
        ),
    ]
    try:
        data = safe_json_parse(llm.invoke(messages).content)
        logger.info("Summarizer: action_items=%d", len(data.get("action_items", [])))
        return {
            "short_summary": data.get("short_summary", ""),
            "detailed_summary": data.get("detailed_summary", ""),
            "action_items": data.get("action_items", []),
            "deadlines": data.get("deadlines", []),
            "meeting_requests": data.get("meeting_requests", []),
            "payment_requests": data.get("payment_requests", []),
            "important_dates": data.get("important_dates", []),
        }
    except Exception as exc:
        logger.error("Summarizer failed: %s", exc)
        return {
            "short_summary": "Summary unavailable.",
            "detailed_summary": "",
            "action_items": [],
            "deadlines": [],
            "meeting_requests": [],
            "payment_requests": [],
            "important_dates": [],
            "error": str(exc),
        }


@mcp.tool(
    description="Performs an extensive security check to compute a threat risk score (0-100), "
                "assign a severity rating (Low, Medium, High, Critical), identify security findings, "
                "and explain potential threats. This tool MUST be called before any trashing, spam-labeling, or replying."
)
def analyze_security(message_id: str = "") -> dict[str, Any]:
    """
    Perform a security and threat analysis on the email using the message_id.

    Args:
        message_id: The Gmail message ID (session key) of the email.
    """
    email_data = get_session_email(message_id)
    if not email_data:
        logger.error("analyze_security: email not found in session cache for message_id=%s", message_id)
        return {
            "security_findings": [],
            "risk_score": 0,
            "severity": "Low",
            "security_explanation": "Email not found in session cache",
        }

    sender = email_data.get("sender", "")
    sender_domain = email_data.get("sender_domain", "")
    subject = email_data.get("subject", "")
    body_text = email_data.get("body_text", "")
    urls_list = email_data.get("urls", [])
    attachments_list = email_data.get("attachments", [])
    headers_dict = email_data.get("headers", {})

    llm = get_llm()
    messages = [
        SystemMessage(content=SECURITY_SYSTEM),
        HumanMessage(
            content=SECURITY_HUMAN.format(
                sender=sender,
                sender_domain=sender_domain,
                subject=subject,
                body=body_text,
                urls=", ".join(urls_list) or "None",
                attachments=", ".join(a.get("filename", "?") for a in attachments_list) or "None",
                headers=json.dumps(headers_dict, indent=2),
            )
        ),
    ]
    try:
        data = safe_json_parse(llm.invoke(messages).content)
        risk_score = max(0, min(100, int(data.get("risk_score", 0))))
        severity = data.get("severity", "Low")
        if severity not in {"Low", "Medium", "High", "Critical"}:
            severity = "Low"
        logger.info(
            "Security: risk=%d severity=%s findings=%d",
            risk_score,
            severity,
            len(data.get("findings", [])),
        )
        return {
            "security_findings": data.get("findings", []),
            "risk_score": risk_score,
            "severity": severity,
            "security_explanation": data.get("explanation", ""),
        }
    except Exception as exc:
        logger.error("Security analysis failed: %s", exc)
        return {
            "security_findings": [],
            "risk_score": 0,
            "severity": "Low",
            "security_explanation": f"Security analysis failed: {exc}",
        }


@mcp.tool(
    description="Expands and analyzes any link/URL in the email body. Checks if it is shortened, "
                "if it uses HTTPS, and whether the domain or URL is flagged as suspicious."
)
def analyze_urls(message_id: str = "") -> dict[str, Any]:
    """
    Perform a detailed analysis of links/URLs in the email using the message_id.

    Args:
        message_id: The Gmail message ID (session key) of the email.
    """
    email_data = get_session_email(message_id)
    if not email_data:
        logger.error("analyze_urls: email not found in session cache for message_id=%s", message_id)
        return {"url_analyses": []}

    urls_list = email_data.get("urls", [])
    if not urls_list:
        logger.info("URL Analysis: no URLs to analyse")
        return {"url_analyses": []}

    results = []
    for url in urls_list:
        analysis = analyze_url(url)
        results.append(analysis)
        if analysis["suspicious"]:
            logger.warning("Suspicious URL: %s — %s", url, ", ".join(analysis["reasons"]))

    logger.info(
        "URL Analysis: total=%d suspicious=%d",
        len(results),
        sum(1 for r in results if r["suspicious"]),
    )
    return {"url_analyses": results}


@mcp.tool(
    description="Inspects email attachment metadata (extension, size, MIME type) and identifies "
                "suspicious extensions or known threats."
)
def analyze_attachments(message_id: str = "") -> dict[str, Any]:
    """
    Analyze the metadata of attachments to check for malicious signatures or extensions using the message_id.

    Args:
        message_id: The Gmail message ID (session key) of the email.
    """
    email_data = get_session_email(message_id)
    if not email_data:
        logger.error("analyze_attachments: email not found in session cache for message_id=%s", message_id)
        return {"attachment_analyses": []}

    attachments_list = email_data.get("attachments", [])
    if not attachments_list:
        logger.info("Attachment Analysis: no attachments")
        return {"attachment_analyses": []}

    results = []
    for att in attachments_list:
        analysis = analyze_attachment(att)
        results.append(analysis)
        if analysis["suspicious"]:
            logger.warning(
                "Suspicious attachment: %s — %s",
                analysis["filename"],
                ", ".join(analysis["reasons"]),
            )

    logger.info(
        "Attachment Analysis: total=%d suspicious=%d",
        len(results),
        sum(1 for r in results if r["suspicious"]),
    )
    return {"attachment_analyses": results}


@mcp.tool(
    description="Searches the web and domain reputation blacklists for scam, phishing, "
                "or spam reports matching the sender or the sender's domain."
)
def search_reputation(message_id: str = "") -> dict[str, Any]:
    """
    Search web resources for sender and domain reputation reports using the message_id.

    Args:
        message_id: The Gmail message ID (session key) of the email.
    """
    email_data = get_session_email(message_id)
    if not email_data:
        logger.error("search_reputation: email not found in session cache for message_id=%s", message_id)
        return {"sender_reputation": "N/A", "domain_reputation": "N/A", "web_search_summary": "No context found"}

    sender = email_data.get("sender", "")
    domain = email_data.get("sender_domain", "")

    sender_results, domain_results = [], []

    if sender:
        query = (
            f'"{sender}" email scam phishing report '
            f"site:reddit.com OR site:spamhaus.org OR site:mxtoolbox.com"
        )
        logger.info("Web search: sender query → %s", query)
        sender_results = web_search(query, max_results=WEB_SEARCH_MAX_RESULTS)

    if domain:
        query = f'"{domain}" email domain reputation scam phishing blacklist'
        logger.info("Web search: domain query → %s", query)
        domain_results = web_search(query, max_results=WEB_SEARCH_MAX_RESULTS)

    sender_reputation = (
        summarize_search_results(sender_results) if sender_results else "No results found."
    )
    domain_reputation = (
        summarize_search_results(domain_results) if domain_results else "No results found."
    )

    logger.info("Web search: done sender=%s domain=%s", sender, domain)
    return {
        "sender_reputation": sender_reputation,
        "domain_reputation": domain_reputation,
        "web_search_summary": f"Sender ({sender}):\n{sender_reputation}\n\nDomain ({domain}):\n{domain_reputation}",
    }


@mcp.tool(
    description="Drafts a suggested email reply using the message_id. Tone defaults to 'professional'."
)
def generate_reply(
    message_id: str = "",
    reply_tone: str = "professional",
) -> dict[str, Any]:
    """
    Draft a suggested reply to the email using the message_id.

    Args:
        message_id: The Gmail message ID (session key) of the email.
        reply_tone: The tone of the reply (e.g. professional, friendly, formal).
    """
    email_data = get_session_email(message_id)
    if not email_data:
        logger.error("generate_reply: email not found in session cache for message_id=%s", message_id)
        return {"suggested_reply": "", "reply_tone": reply_tone}

    sender = email_data.get("sender", "")
    subject = email_data.get("subject", "")
    body_text = email_data.get("body_text", "")

    # Retrieve risk and category from trace log
    trace = get_trace(message_id)
    security_call = next((t for t in trace if t["tool"] in ("analyze_security", "security_analyze")), None)
    risk_score = security_call["result"].get("risk_score", 0) if security_call else 0

    classify_call = next((t for t in trace if t["tool"] in ("classify_email", "classifier")), None)
    category = classify_call["result"].get("category", "Unknown") if classify_call else "Unknown"

    # Retrive summary & action items from trace
    summarize_call = next((t for t in trace if t["tool"] in ("summarize_email", "summarizer")), None)
    short_summary = summarize_call["result"].get("short_summary", "") if summarize_call else ""
    action_items_list = summarize_call["result"].get("action_items", []) if summarize_call else []

    if risk_score >= REPLY_RISK_THRESHOLD or category in _NO_REPLY_CATEGORIES:
        logger.info("Reply: skipped (risk=%d category=%s)", risk_score, category)
        return {"suggested_reply": "", "reply_tone": ""}

    tone = reply_tone or DEFAULT_REPLY_TONE
    llm = get_llm()
    messages = [
        SystemMessage(content=REPLY_SYSTEM.format(tone=tone)),
        HumanMessage(
            content=REPLY_HUMAN.format(
                sender=sender,
                subject=subject,
                body=body_text,
                risk_score=risk_score,
                category=category,
                short_summary=short_summary,
                action_items=", ".join(action_items_list) or "None",
            )
        ),
    ]
    try:
        data = safe_json_parse(llm.invoke(messages).content)
        reply = data.get("suggested_reply", "")
        logger.info("Reply: generated %d chars", len(reply))
        return {"suggested_reply": reply, "reply_tone": tone}
    except Exception as exc:
        logger.error("Reply generation failed: %s", exc)
        return {
            "suggested_reply": "",
            "reply_tone": tone,
            "error": str(exc),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting Analysis MCP server (stdio transport)")
    mcp.run(transport="stdio")
