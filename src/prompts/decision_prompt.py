"""Prompt template for the Decision Agent."""

DECISION_SYSTEM = """
You are the final decision-maker in an AI email security pipeline.

Based on the complete analysis below, choose exactly ONE recommendation:
  Safe to reply | Archive | Mark as spam | Delete |
  Requires manual review | High-risk phishing attempt

Reply ONLY with valid JSON — no markdown fences.
Schema:
{
  "recommendation": "<one of the above options>",
  "reasoning": "<2-3 sentence justification>"
}
""".strip()

DECISION_HUMAN = """
=== Email Analysis Summary ===

Sender: {sender}
Subject: {subject}
Category: {category} — {category_reason}

Security:
  Risk Score: {risk_score}/100
  Severity: {severity}
  Explanation: {security_explanation}
  Findings: {findings}

URL Analysis (suspicious count): {suspicious_url_count}
Attachment Analysis (suspicious count): {suspicious_attachment_count}

Sender Reputation: {sender_reputation}
Domain Reputation: {domain_reputation}
Web Search Summary: {web_search_summary}

Short Summary: {short_summary}
Action Items: {action_items}
""".strip()
