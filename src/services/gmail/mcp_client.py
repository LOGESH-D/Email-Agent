"""
services/gmail/mcp_client.py — MCP client for the Gmail Actions MCP server.

Connects to the Gmail MCP server (mcp_server.py) via in-process transport
and calls tools by name over the MCP protocol using FastMCP v3.

Usage:
    from src.services.gmail.mcp_client import call_gmail_tool

    result = call_gmail_tool("mark_as_read", {"message_id": "abc123"})
    result = call_gmail_tool("send_reply", {
        "thread_id":    "...",
        "to":           "sender@example.com",
        "subject":      "Re: Hello",
        "body":         "Thank you for reaching out.",
        "sender_email": "you@gmail.com",
    })
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


def call_gmail_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Call a Gmail MCP tool by name with the given arguments.

    Uses FastMCP's in-process Client — no separate server process needed.
    The MCP server (mcp_server.py) runs in the same Python process.

    Args:
        tool_name  : Name of the MCP tool (e.g. "send_reply", "mark_as_read").
        arguments  : Dict of arguments matching the tool's input schema.

    Returns:
        Tool result as a dict. Always returns a dict — never raises on tool errors.

    Raises:
        RuntimeError : If the MCP call itself fails (not a tool-level error).
    """
    return asyncio.run(_call_tool_async(tool_name, arguments))


async def _call_tool_async(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Async implementation — uses FastMCP v3 CallToolResult API."""
    from fastmcp import Client  # type: ignore
    from src.services.gmail.mcp_server import mcp

    async with Client(mcp) as client:
        logger.debug("MCP call: tool=%s args=%s", tool_name, arguments)

        result = await client.call_tool(tool_name, arguments)

        # FastMCP v3: result is a CallToolResult object
        # .is_error  — True if the tool raised an exception
        # .data      — the direct return value of the tool function
        # .content   — list of TextContent items (raw MCP content)

        if result.is_error:
            # Extract error message from content
            error_text = ""
            if result.content:
                error_text = getattr(result.content[0], "text", str(result.content[0]))
            logger.error("MCP tool '%s' returned error: %s", tool_name, error_text)
            raise RuntimeError(f"MCP tool '{tool_name}' error: {error_text}")

        # .data is the Python return value of the tool function
        data = result.data
        if isinstance(data, dict):
            logger.debug("MCP result: tool=%s → %s", tool_name, data)
            return data

        # Fallback: wrap primitive return in a dict
        return {"result": data, "status": "done"}
