"""
agent/orchestrator.py — ReAct-style supervisor agent for email triage and security.

Replaces pipeline/graph.py. Runs a dynamic loop calling LLM with MCP tools,
updating the local state, and generating the final structured report.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

from src.core.config import DEFAULT_REPLY_TONE
from src.core.utils import get_llm, safe_json_parse
from src.agent.parser import parse_email
from src.agent.mcp_registry import MCPRegistry
from src.agent.trace import init_session_trace, clear_session_trace

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10

SYSTEM_PROMPT = """You are the Supervisor Agent of a secure email triage assistant.
Your goal is to inspect incoming emails, classify them, perform security checks, and execute appropriate Gmail actions.

Available tools include:
- `classify_email`: Classifies email into standard categories. Run this early!
- `summarize_email`: Summarizes email and extracts dates/action items.
- `analyze_security`: Performs a threat analysis, giving a risk score and severity. Run this before trashing/spamming/replying!
- `analyze_urls`: Analyzes extracted URLs.
- `analyze_attachments`: Analyzes attachments for potential malware.
- `search_reputation`: Checks reputation of sender and domain.
- `generate_reply`: Drafts a reply (if safe).
- Gmail action tools: `send_reply`, `label_as_spam`, `move_to_trash`, `archive_email`, `add_label`, `mark_as_read`, `mark_as_unread`.

CRITICAL SAFETY & ROUTING RULES:
1. You MUST investigate the email using analysis tools before taking actions.
2. Specifically, you MUST call `analyze_security` before calling `move_to_trash`, `label_as_spam`, or `send_reply`.
3. The tools enforce authorization boundaries at the tool layer:
   - `move_to_trash` refuses to execute unless a security check was run and risk score is high (>=90).
   - `label_as_spam` refuses to execute unless a security check was run and risk score is medium-high (>=75).
   - `send_reply` refuses to execute if risk score is elevated (>=40) or if the category is Spam, Newsletter, Promotion, or Shopping.
4. Optimize efficiency:
   - Skip reputation search or URL check if early signals (e.g. security analysis) already flag the email as Critical severity or risk >= 90.
   - If an email is benign (risk < 40) and you want to reply, you must first call `generate_reply` to obtain the suggestion before calling `send_reply`.
5. Make decisions yourself:
   - For spam category: call `label_as_spam`.
   - For high-risk phishing: call `move_to_trash` and `add_label` (with "Phishing Detected").
   - For newsletter/promotions/shopping: call `archive_email` and `mark_as_read`.
   - For safe/work/personal emails needing reply: call `send_reply` (with the suggestion generated) and `mark_as_read`.
   - For uncertain cases: call `add_label` (with "Needs Review") and `mark_as_unread`.
6. Parameter rules:
   - All analysis tools (`classify_email`, `summarize_email`, `analyze_security`, `analyze_urls`, `analyze_attachments`, `search_reputation`, `generate_reply`) only require a single parameter: `message_id`. You MUST pass the current Gmail message ID as the `message_id` argument to these tools.
   - `send_reply` only requires `thread_id` and `body`.
   - Gmail action tools (like `move_to_trash`, `label_as_spam`, `archive_email`, etc.) only require `message_id`.

When you are done investigating and executing actions, output a final JSON block summarizing your decision.
Use this exact format:
```json
{
  "recommendation": "<one of: Safe to reply, Archive, Mark as spam, Delete, Requires manual review, High-risk phishing attempt>",
  "reasoning": "<2-3 sentence explanation of the findings and actions taken>"
}
```
"""


def run_email_agent(
    email: dict[str, Any],
    gmail_message_id: str = "",
    gmail_thread_id: str = "",
    history_id: str = "",
    reply_tone: str = DEFAULT_REPLY_TONE,
) -> dict[str, Any]:
    """
    Run the agentic ReAct supervisor loop on a fetched Gmail email.

    Replaces the LangGraph graph execution.
    """
    return asyncio.run(
        _run_email_agent_async(
            email=email,
            gmail_message_id=gmail_message_id,
            gmail_thread_id=gmail_thread_id,
            history_id=history_id,
            reply_tone=reply_tone,
        )
    )


async def _run_email_agent_async(
    email: dict[str, Any],
    gmail_message_id: str,
    gmail_thread_id: str,
    history_id: str,
    reply_tone: str,
) -> dict[str, Any]:
    # 1. Parse raw email deterministically
    state: dict[str, Any] = {
        "gmail_message_id": gmail_message_id,
        "gmail_thread_id": gmail_thread_id,
        "history_id": history_id,
        "raw_email": email,
        "sender": "",
        "sender_domain": "",
        "recipients": [],
        "subject": "",
        "body_text": "",
        "body_html": "",
        "urls": [],
        "attachments": [],
        "headers": {},
        "metadata": {},
        "category": "",
        "category_reason": "",
        "short_summary": "",
        "detailed_summary": "",
        "action_items": [],
        "deadlines": [],
        "meeting_requests": [],
        "payment_requests": [],
        "important_dates": [],
        "security_findings": [],
        "risk_score": 0,
        "severity": "Low",
        "security_explanation": "",
        "url_analyses": [],
        "attachment_analyses": [],
        "sender_reputation": "",
        "domain_reputation": "",
        "web_search_summary": "",
        "reply_tone": reply_tone,
        "suggested_reply": "",
        "recommendation": "",
        "recommendation_reasoning": "",
        "mcp_actions_taken": [],
        "error_messages": [],
    }

    try:
        parsed = parse_email(state)
        state.update(parsed)
    except Exception as exc:
        logger.exception("Parser failed: %s", exc)
        state["error_messages"].append(f"Parser error: {exc}")

    session_key = gmail_message_id or gmail_thread_id or "session-unknown"
    init_session_trace(gmail_message_id, gmail_thread_id, email_data=state)

    # 2. Build Tool Registry and connect to servers
    registry = MCPRegistry()
    await registry.initialize()

    # 3. Prepare Chat model with bound tools
    llm = get_llm()
    llm_with_tools = llm.bind_tools(registry.tools_schema)

    initial_human_prompt = (
        f"Analyze this email:\n"
        f"Sender: {state['sender']}\n"
        f"Domain: {state['sender_domain']}\n"
        f"Subject: {state['subject']}\n"
        f"Body Text: {state['body_text'][:1500]}\n"
        f"URLs: {state['urls']}\n"
        f"Attachments: {[a.get('filename') for a in state['attachments']]}\n"
        f"Headers: {state['headers']}\n"
        f"Gmail Message ID: {gmail_message_id}\n"
        f"Gmail Thread ID: {gmail_thread_id}\n"
    )

    messages: list[Any] = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=initial_human_prompt),
    ]

    iterations = 0
    mcp_actions_taken: list[dict[str, Any]] = []

    logger.info("Supervisor loop started for message_id=%s", gmail_message_id)

    while iterations < MAX_ITERATIONS:
        try:
            response = await llm_with_tools.ainvoke(messages)
        except Exception as exc:
            logger.exception("LLM invocation failed: %s", exc)
            state["error_messages"].append(f"LLM error: {exc}")
            break

        messages.append(response)

        # Check if the LLM generated any tool calls
        if not response.tool_calls:
            logger.info("Supervisor finished calling tools at iteration %d", iterations)
            break

        # Process tool calls in parallel or sequentially (sequential is safer for trace checks)
        tool_messages = []
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            try:
                # Execute tool using registry
                result = await registry.execute_tool(tool_name, tool_args, session_key)

                # Track Gmail actions for report
                if tool_name in (
                    "send_reply",
                    "label_as_spam",
                    "move_to_trash",
                    "archive_email",
                    "add_label",
                    "mark_as_read",
                    "mark_as_unread",
                ):
                    status_val = result.get("status", "done")
                    detail_val = result.get("detail") or result.get("reason") or result.get("error") or "Success"
                    mcp_actions_taken.append(
                        {
                            "action": tool_name,
                            "status": status_val,
                            "detail": detail_val,
                        }
                    )

                # Update local state fields from tool outputs
                if tool_name == "classify_email":
                    state["category"] = result.get("category", "Unknown")
                    state["category_reason"] = result.get("category_reason", "")
                elif tool_name == "summarize_email":
                    state["short_summary"] = result.get("short_summary", "")
                    state["detailed_summary"] = result.get("detailed_summary", "")
                    state["action_items"] = result.get("action_items", [])
                    state["deadlines"] = result.get("deadlines", [])
                    state["meeting_requests"] = result.get("meeting_requests", [])
                    state["payment_requests"] = result.get("payment_requests", [])
                    state["important_dates"] = result.get("important_dates", [])
                elif tool_name == "analyze_security":
                    state["risk_score"] = result.get("risk_score", 0)
                    state["severity"] = result.get("severity", "Low")
                    state["security_explanation"] = result.get("security_explanation", "")
                    state["security_findings"] = result.get("security_findings", [])
                elif tool_name == "analyze_urls":
                    state["url_analyses"] = result.get("url_analyses", []) or result.get("result", [])
                elif tool_name == "analyze_attachments":
                    state["attachment_analyses"] = result.get("attachment_analyses", []) or result.get("result", [])
                elif tool_name == "search_reputation":
                    state["sender_reputation"] = result.get("sender_reputation", "")
                    state["domain_reputation"] = result.get("domain_reputation", "")
                    state["web_search_summary"] = result.get("web_search_summary", "")
                elif tool_name == "generate_reply":
                    state["suggested_reply"] = result.get("suggested_reply", "")
                    state["reply_tone"] = result.get("reply_tone", "")

                tool_messages.append(
                    ToolMessage(content=json.dumps(result), tool_call_id=tool_id, name=tool_name)
                )

            except Exception as exc:
                logger.error("Error executing tool '%s': %s", tool_name, exc)
                state["error_messages"].append(f"Tool {tool_name} error: {exc}")

                if tool_name in (
                    "send_reply",
                    "label_as_spam",
                    "move_to_trash",
                    "archive_email",
                    "add_label",
                    "mark_as_read",
                    "mark_as_unread",
                ):
                    mcp_actions_taken.append(
                        {
                            "action": tool_name,
                            "status": "failed",
                            "detail": str(exc),
                        }
                    )

                tool_messages.append(
                    ToolMessage(
                        content=json.dumps({"status": "error", "message": str(exc)}),
                        tool_call_id=tool_id,
                        name=tool_name,
                    )
                )

        messages.extend(tool_messages)
        iterations += 1

    # 4. Parse the final decision recommendation and reasoning
    recommendation = "Requires manual review"
    reasoning = "Supervisor loop ended without producing an explicit JSON recommendation."

    last_message = messages[-1]
    if isinstance(last_message, AIMessage) and last_message.content:
        content_text = last_message.content
        parsed_json = safe_json_parse(content_text)
        if parsed_json and "recommendation" in parsed_json:
            recommendation = parsed_json.get("recommendation", "Requires manual review")
            reasoning = parsed_json.get("reasoning", "")
        else:
            # Simple regex search fallback
            import re
            rec_match = re.search(r'"recommendation"\s*:\s*"([^"]+)"', content_text, re.IGNORECASE)
            reas_match = re.search(r'"reasoning"\s*:\s*"([^"]+)"', content_text, re.IGNORECASE)
            if rec_match:
                recommendation = rec_match.group(1).strip()
            if reas_match:
                reasoning = reas_match.group(1).strip()

    # Heuristic verification & cleanup
    VALID_RECOMMENDATIONS = {
        "Safe to reply",
        "Archive",
        "Mark as spam",
        "Delete",
        "Requires manual review",
        "High-risk phishing attempt",
    }
    if recommendation not in VALID_RECOMMENDATIONS:
        logger.warning("Parsed recommendation '%s' is invalid. Using heuristics.", recommendation)
        called_tools = [act["action"] for act in mcp_actions_taken if act["status"] in ("done", "sent", "trashed", "labeled", "archived")]
        if "move_to_trash" in called_tools and any(act["action"] == "add_label" and "phishing" in str(act.get("detail", "")).lower() for act in mcp_actions_taken):
            recommendation = "High-risk phishing attempt"
        elif "move_to_trash" in called_tools:
            recommendation = "Delete"
        elif "label_as_spam" in called_tools:
            recommendation = "Mark as spam"
        elif "archive_email" in called_tools:
            recommendation = "Archive"
        elif "send_reply" in called_tools:
            recommendation = "Safe to reply"
        else:
            recommendation = "Requires manual review"

        reasoning = f"Inferred recommendation from executed actions: {', '.join(called_tools) or 'none'}."

    state["recommendation"] = recommendation
    state["recommendation_reasoning"] = reasoning
    state["mcp_actions_taken"] = mcp_actions_taken

    # 5. Build and return the final report matching expected schema
    final_report = {
        "gmail": {
            "message_id": gmail_message_id,
            "thread_id": gmail_thread_id,
        },
        "email_metadata": {
            "sender": state["sender"],
            "sender_domain": state["sender_domain"],
            "recipients": state["recipients"],
            "subject": state["subject"],
        },
        "classification": {
            "category": state["category"] or "Unknown",
            "reason": state["category_reason"],
        },
        "summary": {
            "short": state["short_summary"],
            "detailed": state["detailed_summary"],
            "action_items": state["action_items"],
            "deadlines": state["deadlines"],
            "meeting_requests": state["meeting_requests"],
            "payment_requests": state["payment_requests"],
            "important_dates": state["important_dates"],
        },
        "security": {
            "risk_score": state["risk_score"],
            "severity": state["severity"],
            "explanation": state["security_explanation"],
            "findings": state["security_findings"],
        },
        "url_analysis": state["url_analyses"],
        "attachment_analysis": state["attachment_analyses"],
        "reputation": {
            "sender_reputation": state["sender_reputation"],
            "domain_reputation": state["domain_reputation"],
            "web_search_summary": state["web_search_summary"],
        },
        "suggested_reply": {
            "tone": state["reply_tone"],
            "draft": state["suggested_reply"],
        },
        "decision": {
            "recommendation": state["recommendation"],
            "reasoning": state["recommendation_reasoning"],
        },
        "mcp_actions": state["mcp_actions_taken"],
        "errors": state["error_messages"],
    }

    clear_session_trace(gmail_message_id, gmail_thread_id)
    logger.info(
        "Done agentic run | message_id=%s rec='%s' risk=%d actions=%d",
        gmail_message_id,
        recommendation,
        state["risk_score"],
        len(mcp_actions_taken),
    )

    return final_report
