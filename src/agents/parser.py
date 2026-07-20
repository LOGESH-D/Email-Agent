"""Agent 1 — Email Parser Agent"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.core.state import EmailState

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def _extract_urls_from_text(text: str) -> list[str]:
    return list(dict.fromkeys(_URL_RE.findall(text)))


def _extract_urls_from_html(html: str) -> list[str]:
    pattern = re.compile(r'(?:href|src)\s*=\s*["\']?(https?://[^\s"\'<>]+)', re.IGNORECASE)
    return list(dict.fromkeys(pattern.findall(html)))


def _get_sender_domain(sender: str) -> str:
    match = re.search(r"@([\w.\-]+)", sender)
    return match.group(1).lower() if match else ""


def parse_email(state: EmailState) -> dict:
    """LangGraph node: parse raw_email and return only parsed fields."""
    raw: dict[str, Any] = state.get("raw_email", {})

    if not raw:
        logger.error("parse_email: raw_email is empty")
        return {"error_messages": state.get("error_messages", []) + ["Parser: raw_email is empty"]}

    sender     = raw.get("sender", "")
    recipients = raw.get("recipients", [])
    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.split(",")]

    subject     = raw.get("subject", "")
    body_text   = raw.get("body_text", raw.get("body", ""))
    body_html   = raw.get("body_html", "")
    attachments = raw.get("attachments", [])
    headers     = raw.get("headers", {})
    metadata    = raw.get("metadata", {})

    provided_urls = raw.get("urls", [])
    text_urls     = _extract_urls_from_text(body_text)
    html_urls     = _extract_urls_from_html(body_html)
    all_urls      = list(dict.fromkeys(provided_urls + text_urls + html_urls))

    sender_domain = raw.get("sender_domain", "") or _get_sender_domain(sender)

    logger.info("Parser: sender=%s domain=%s urls=%d attachments=%d",
                sender, sender_domain, len(all_urls), len(attachments))

    return {
        "sender": sender, "sender_domain": sender_domain,
        "recipients": recipients, "subject": subject,
        "body_text": body_text, "body_html": body_html,
        "urls": all_urls, "attachments": attachments,
        "headers": headers, "metadata": metadata,
    }
