"""
services/gmail/mcp_server.py — Real MCP server exposing Gmail actions as tools.

Uses FastMCP to create a proper Model Context Protocol server.
Every Gmail action is registered as an MCP tool with a name, description,
and typed input schema. The MCP client (mcp_client.py) calls these tools
by name over the MCP protocol.

Tools exposed:
  - send_reply
  - label_as_spam
  - move_to_trash
  - archive_email
  - add_label
  - mark_as_read
  - mark_as_unread

Run standalone (for testing):
    python -m src.services.gmail.mcp_server

The webhook server starts this automatically in a background thread.
"""

from __future__ import annotations

import base64
import logging
import re
from email.mime.text import MIMEText

from fastmcp import FastMCP  # type: ignore

from src.core.config import (
    GMAIL_ADDRESS,
    LABEL_NEEDS_REVIEW,
    LABEL_PHISHING_DETECTED,
)
from src.services.gmail.transport import _purge_proxy_env

logger = logging.getLogger(__name__)

# ── MCP server instance ───────────────────────────────────────────────────────
mcp = FastMCP(
    name="gmail-actions",
    instructions=(
        "Gmail action tools for the Mail Analyzer Agent. "
        "Provides tools to send replies, label, archive, trash, "
        "and mark emails via the Gmail API."
    ),
)

# ── Deduplication guard ───────────────────────────────────────────────────────
_replied_threads: set[str] = set()


# ── Internal helpers (not exposed as MCP tools) ───────────────────────────────

def _get_service():
    """Return a proxy-free Gmail API service."""
    _purge_proxy_env()
    from src.services.gmail.auth import get_gmail_service
    return get_gmail_service()


def _modify_labels(
    message_id: str,
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
) -> dict:
    _purge_proxy_env()
    service = _get_service()
    body: dict = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels
    return service.users().messages().modify(userId="me", id=message_id, body=body).execute()


def _get_or_create_label(label_name: str) -> str:
    service  = _get_service()
    existing = service.users().labels().list(userId="me").execute()
    for lbl in existing.get("labels", []):
        if lbl["name"].lower() == label_name.lower():
            return lbl["id"]
    new_label = service.users().labels().create(userId="me", body={"name": label_name}).execute()
    logger.info("Created Gmail label: %s (id=%s)", label_name, new_label["id"])
    return new_label["id"]


# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool(
    description="Send a reply to a Gmail thread. "
                "Skips duplicate replies to the same thread. "
                "Rejects replies containing placeholder text like [your name]."
)
def send_reply(
    thread_id: str = "",
    body: str = "",
) -> dict:
    """
    Send a reply in an existing Gmail thread.

    Args:
        thread_id : Gmail thread ID to reply in.
        body      : Plain-text reply body.

    Returns:
        dict with status "sent", "skipped", or raises ValueError for bad content.
    """
    # ── Guardrails Check ──
    from src.agent.trace import get_trace, get_session_email
    from src.core.config import REPLY_RISK_THRESHOLD

    trace = get_trace(thread_id)
    security_call = next((t for t in trace if t["tool"] in ("analyze_security", "security_analyze")), None)
    if not security_call:
        return {"status": "refused", "reason": "send_reply refused: analyze_security must be called first in this session."}
    
    risk_score = security_call["result"].get("risk_score", 0)
    if risk_score >= REPLY_RISK_THRESHOLD:
        return {
            "status": "refused",
            "reason": f"send_reply refused: security risk score ({risk_score}) is equal to or above REPLY_RISK_THRESHOLD ({REPLY_RISK_THRESHOLD})."
        }

    classify_call = next((t for t in trace if t["tool"] in ("classify_email", "classifier")), None)
    if classify_call:
        category = classify_call["result"].get("category", "Unknown")
        if category in {"Spam", "Newsletter", "Promotion", "Shopping"}:
            logger.warning("MCP send_reply: category '%s' is restricted. Skipping reply.", category)
            return {"status": "skipped", "reason": f"Category '{category}' is restricted from auto-replies"}

    # ── Resolve email details from cache ──
    email_data = get_session_email(thread_id)
    if not email_data:
        raise ValueError(f"send_reply refused: email data not found in cache for thread_id={thread_id}")

    to = email_data.get("sender", "")
    subject = email_data.get("subject", "")

    # ── Simulation Bypass ──
    if thread_id.startswith("sim-") or thread_id.startswith("test-"):
        logger.info("MCP send_reply: mock reply sent (simulation) in thread=%s to=%s", thread_id, to)
        return {"status": "sent", "message_id": "sim-reply-id", "detail": "Mock reply sent (simulation)"}

    _purge_proxy_env()

    if thread_id in _replied_threads:
        logger.warning("MCP send_reply: skipping duplicate thread_id=%s", thread_id)
        return {"status": "skipped", "reason": "already replied to this thread"}

    _replied_threads.add(thread_id)
    if len(_replied_threads) > 500:
        _replied_threads.discard(next(iter(_replied_threads)))

    if re.compile(r'\[.{3,60}\]').search(body):
        _replied_threads.discard(thread_id)
        raise ValueError(
            "Reply body contains placeholder text (e.g. [your name]). "
            "The LLM must generate a complete reply without placeholders."
        )

    service = _get_service()
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    mime_msg = MIMEText(body, "plain")
    mime_msg["to"]      = to
    mime_msg["from"]    = GMAIL_ADDRESS
    mime_msg["subject"] = subject

    raw    = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me", body={"raw": raw, "threadId": thread_id}
    ).execute()

    logger.info("MCP send_reply: sent in thread=%s to=%s", thread_id, to)
    return {"status": "sent", "message_id": result.get("id", "")}


@mcp.tool(
    description="Apply the SPAM label to a Gmail message and remove it from the inbox."
)
def label_as_spam(message_id: str = "") -> dict:
    """
    Mark a Gmail message as spam.

    Args:
        message_id : Gmail message ID to label as spam.

    Returns:
        Gmail API modify response dict.
    """
    # ── Guardrails Check ──
    from src.agent.trace import get_trace
    from src.core.config import AUTO_SPAM_THRESHOLD

    trace = get_trace(message_id)
    security_call = next((t for t in trace if t["tool"] in ("analyze_security", "security_analyze")), None)
    if not security_call:
        return {"status": "refused", "reason": "label_as_spam refused: analyze_security must be called first in this session."}
    
    risk_score = security_call["result"].get("risk_score", 0)
    if risk_score < AUTO_SPAM_THRESHOLD:
        return {
            "status": "refused",
            "reason": f"label_as_spam refused: security risk score ({risk_score}) is below AUTO_SPAM_THRESHOLD ({AUTO_SPAM_THRESHOLD})."
        }

    # ── Simulation Bypass ──
    if message_id.startswith("sim-") or message_id.startswith("test-"):
        logger.info("MCP label_as_spam: mock spam label applied (simulation) message_id=%s", message_id)
        return {"status": "labeled", "detail": "Mock spam label applied (simulation)"}

    result = _modify_labels(message_id, add_labels=["SPAM"], remove_labels=["INBOX"])
    logger.info("MCP label_as_spam: message_id=%s", message_id)
    return result


@mcp.tool(
    description="Move a Gmail message to Trash."
)
def move_to_trash(message_id: str = "") -> dict:
    """
    Move a Gmail message to the Trash folder.

    Args:
        message_id : Gmail message ID to trash.

    Returns:
        Gmail API trash response dict.
    """
    # ── Guardrails Check ──
    from src.agent.trace import get_trace
    from src.core.config import AUTO_DELETE_THRESHOLD

    trace = get_trace(message_id)
    security_call = next((t for t in trace if t["tool"] in ("analyze_security", "security_analyze")), None)
    if not security_call:
        return {"status": "refused", "reason": "move_to_trash refused: analyze_security must be called first in this session."}
    
    risk_score = security_call["result"].get("risk_score", 0)
    if risk_score < AUTO_DELETE_THRESHOLD:
        return {
            "status": "refused",
            "reason": f"move_to_trash refused: security risk score ({risk_score}) is below AUTO_DELETE_THRESHOLD ({AUTO_DELETE_THRESHOLD})."
        }

    # ── Simulation Bypass ──
    if message_id.startswith("sim-") or message_id.startswith("test-"):
        logger.info("MCP move_to_trash: mock moved to trash (simulation) message_id=%s", message_id)
        return {"status": "trashed", "detail": "Mock moved to trash (simulation)"}

    _purge_proxy_env()
    result = _get_service().users().messages().trash(userId="me", id=message_id).execute()
    logger.info("MCP move_to_trash: message_id=%s", message_id)
    return result


@mcp.tool(
    description="Archive a Gmail message by removing it from the inbox (keeps it in All Mail)."
)
def archive_email(message_id: str = "") -> dict:
    """
    Archive a Gmail message — removes the INBOX label.

    Args:
        message_id : Gmail message ID to archive.

    Returns:
        Gmail API modify response dict.
    """
    # ── Simulation Bypass ──
    if message_id.startswith("sim-") or message_id.startswith("test-"):
        logger.info("MCP archive_email: mock email archived (simulation) message_id=%s", message_id)
        return {"status": "archived", "detail": "Mock email archived (simulation)"}

    result = _modify_labels(message_id, remove_labels=["INBOX"])
    logger.info("MCP archive_email: message_id=%s", message_id)
    return result


@mcp.tool(
    description="Apply a named label to a Gmail message. Creates the label if it does not exist."
)
def add_label(message_id: str = "", label_name: str = "") -> dict:
    """
    Apply a custom label to a Gmail message.

    Args:
        message_id : Gmail message ID to label.
        label_name : Label name to apply (created automatically if missing).

    Returns:
        Gmail API modify response dict.
    """
    # ── Simulation Bypass ──
    if message_id.startswith("sim-") or message_id.startswith("test-"):
        logger.info("MCP add_label: mock label '%s' applied (simulation) message_id=%s", label_name, message_id)
        return {"status": "labeled", "label": label_name, "detail": "Mock label applied (simulation)"}

    label_id = _get_or_create_label(label_name)
    result   = _modify_labels(message_id, add_labels=[label_id])
    logger.info("MCP add_label: '%s' → message_id=%s", label_name, message_id)
    return result


@mcp.tool(
    description="Mark a Gmail message as read by removing the UNREAD label."
)
def mark_as_read(message_id: str = "") -> dict:
    """
    Mark a Gmail message as read.

    Args:
        message_id : Gmail message ID to mark as read.

    Returns:
        Gmail API modify response dict.
    """
    # ── Simulation Bypass ──
    if message_id.startswith("sim-") or message_id.startswith("test-"):
        logger.info("MCP mark_as_read: mock marked as read (simulation) message_id=%s", message_id)
        return {"status": "read", "detail": "Mock marked as read (simulation)"}

    result = _modify_labels(message_id, remove_labels=["UNREAD"])
    logger.info("MCP mark_as_read: message_id=%s", message_id)
    return result


@mcp.tool(
    description="Mark a Gmail message as unread by adding the UNREAD label."
)
def mark_as_unread(message_id: str = "") -> dict:
    """
    Mark a Gmail message as unread.

    Args:
        message_id : Gmail message ID to mark as unread.

    Returns:
        Gmail API modify response dict.
    """
    # ── Simulation Bypass ──
    if message_id.startswith("sim-") or message_id.startswith("test-"):
        logger.info("MCP mark_as_unread: mock marked as unread (simulation) message_id=%s", message_id)
        return {"status": "unread", "detail": "Mock marked as unread (simulation)"}

    result = _modify_labels(message_id, add_labels=["UNREAD"])
    logger.info("MCP mark_as_unread: message_id=%s", message_id)
    return result


# ── Standalone entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting Gmail MCP server (stdio transport)")
    mcp.run(transport="stdio")
