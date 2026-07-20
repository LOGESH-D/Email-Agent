"""
Shared state for the Email Security & Assistant Agent workflow.

Every agent reads from and writes to this TypedDict.
Each agent is responsible for updating only its own fields.
"""

from typing import Any, Optional
from typing_extensions import TypedDict


class URLAnalysis(TypedDict):
    url: str
    is_https: bool
    is_shortened: bool
    domain: str
    suspicious: bool
    reasons: list[str]
    final_url: Optional[str]


class AttachmentAnalysis(TypedDict):
    filename: str
    extension: str
    mime_type: str
    size_bytes: Optional[int]
    suspicious: bool
    reasons: list[str]


class SecurityFinding(TypedDict):
    threat_type: str
    description: str
    confidence: str  # low / medium / high


class MCPAction(TypedDict):
    action: str        # e.g. label_spam, send_reply, delete, archive, add_label
    status: str        # pending / done / failed
    detail: str        # human-readable result or error


class EmailState(TypedDict):
    # ── Gmail source identifiers ──────────────────────────────
    gmail_message_id: str       # Gmail message ID from Pub/Sub notification
    gmail_thread_id: str        # Gmail thread ID
    history_id: str             # Gmail historyId from the Pub/Sub push

    # ── Raw email dict (populated by gmail fetcher) ────────────
    raw_email: dict[str, Any]

    # ── Parsed fields (Agent 1 — Parser) ──────────────────────
    sender: str
    sender_domain: str
    recipients: list[str]
    subject: str
    body_text: str
    body_html: str
    urls: list[str]
    attachments: list[dict[str, Any]]
    headers: dict[str, str]
    metadata: dict[str, Any]

    # ── Classification (Agent 2) ───────────────────────────────
    category: str               # Work / Personal / Finance / …
    category_reason: str

    # ── Summary (Agent 3) ──────────────────────────────────────
    short_summary: str
    detailed_summary: str
    action_items: list[str]
    deadlines: list[str]
    meeting_requests: list[str]
    payment_requests: list[str]
    important_dates: list[str]

    # ── Security Analysis (Agent 4) ────────────────────────────
    security_findings: list[SecurityFinding]
    risk_score: int             # 0–100
    severity: str               # Low / Medium / High / Critical
    security_explanation: str

    # ── URL Analysis (Agent 5) ─────────────────────────────────
    url_analyses: list[URLAnalysis]

    # ── Attachment Analysis (Agent 6) ──────────────────────────
    attachment_analyses: list[AttachmentAnalysis]

    # ── Web / Reputation Search (Agent 7) ─────────────────────
    sender_reputation: str
    domain_reputation: str
    web_search_summary: str

    # ── Reply Suggestion (Agent 8) ─────────────────────────────
    reply_tone: str             # professional / friendly / formal
    suggested_reply: str

    # ── Final Decision (Agent 9) ───────────────────────────────
    recommendation: str
    recommendation_reasoning: str

    # ── MCP Gmail Actions (Agent 10 — Action Executor) ─────────
    mcp_actions_taken: list[MCPAction]

    # ── Final report ───────────────────────────────────────────
    final_report: dict[str, Any]

    # ── Internal routing flags ─────────────────────────────────
    error_messages: list[str]
