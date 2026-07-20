"""
services/gmail/fetcher.py — Fetch a full email from Gmail by message ID.
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Any

from src.services.gmail.auth import get_gmail_service
from src.services.gmail.transport import _purge_proxy_env

logger = logging.getLogger(__name__)


def _decode_body(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_parts(payload: dict, body_text: list, body_html: list, attachments: list) -> None:
    mime  = payload.get("mimeType", "")
    parts = payload.get("parts", [])
    body  = payload.get("body", {})

    if mime == "text/plain" and body.get("data"):
        body_text.append(_decode_body(body["data"]))
    elif mime == "text/html" and body.get("data"):
        body_html.append(_decode_body(body["data"]))
    elif body.get("attachmentId"):
        attachments.append({
            "filename":      payload.get("filename", "unknown"),
            "mime_type":     mime,
            "attachment_id": body["attachmentId"],
            "size_bytes":    body.get("size"),
        })

    for part in parts:
        _extract_parts(part, body_text, body_html, attachments)


def _parse_headers(headers: list[dict]) -> dict[str, str]:
    return {h["name"]: h["value"] for h in headers}


def fetch_email(message_id: str) -> dict[str, Any]:
    """Fetch a single Gmail message by ID and return a structured dict."""
    _purge_proxy_env()
    service = get_gmail_service()

    msg     = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    payload = msg.get("payload", {})
    headers = _parse_headers(payload.get("headers", []))

    body_text_parts: list[str] = []
    body_html_parts: list[str] = []
    attachments:     list[dict] = []
    _extract_parts(payload, body_text_parts, body_html_parts, attachments)

    body_text = "\n".join(body_text_parts).strip()
    body_html = "\n".join(body_html_parts).strip()

    sender     = headers.get("From", "")
    to         = headers.get("To", "")
    cc         = headers.get("Cc", "")
    subject    = headers.get("Subject", "(no subject)")
    recipients = [a.strip() for field in [to, cc] if field for a in field.split(",") if a.strip()]

    urls: list[str] = []
    if body_html:
        urls = list(dict.fromkeys(re.findall(r'https?://[^\s"\'<>]+', body_html, re.IGNORECASE)))

    metadata = {
        "gmail_id":      msg.get("id", ""),
        "thread_id":     msg.get("threadId", ""),
        "label_ids":     msg.get("labelIds", []),
        "snippet":       msg.get("snippet", ""),
        "internal_date": msg.get("internalDate", ""),
        "size_estimate": msg.get("sizeEstimate", 0),
    }

    logger.info("Fetched email id=%s subject='%s' from='%s' attachments=%d",
                message_id, subject, sender, len(attachments))

    return {
        "sender": sender, "recipients": recipients, "subject": subject,
        "body_text": body_text, "body_html": body_html,
        "attachments": attachments, "headers": headers,
        "urls": urls, "metadata": metadata,
    }
