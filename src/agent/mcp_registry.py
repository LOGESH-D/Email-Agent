"""
agent/mcp_registry.py — Registry for connecting to Gmail and Analysis MCP servers.

Connects to both servers in-process, collects schemas, and routes tool calls.
Tracks all tool calls in the session trace for safety checking.
"""

from __future__ import annotations

import logging
from typing import Any
from fastmcp import Client  # type: ignore

from src.services.gmail.mcp_server import mcp as gmail_mcp
from src.mcp.analysis_server import mcp as analysis_mcp
from src.agent.trace import add_trace_entry

logger = logging.getLogger(__name__)


class MCPRegistry:
    def __init__(self) -> None:
        self.gmail_mcp = gmail_mcp
        self.analysis_mcp = analysis_mcp
        self.tools_schema: list[dict[str, Any]] = []
        self._tool_to_server: dict[str, str] = {}

    async def initialize(self) -> None:
        """List all tools from both servers in-process and register them."""
        # 1. Load Gmail actions tools
        async with Client(self.gmail_mcp) as client:
            gmail_tools = await client.list_tools()
            for t in gmail_tools:
                self._tool_to_server[t.name] = "gmail"
                self.tools_schema.append(self._convert_to_openai_schema(t))

        # 2. Load Analysis tools
        async with Client(self.analysis_mcp) as client:
            analysis_tools = await client.list_tools()
            for t in analysis_tools:
                self._tool_to_server[t.name] = "analysis"
                self.tools_schema.append(self._convert_to_openai_schema(t))

        logger.info(
            "MCPRegistry: Successfully loaded %d tools from in-process servers.",
            len(self.tools_schema),
        )

    def _convert_to_openai_schema(self, tool: Any) -> dict[str, Any]:
        """Convert a FastMCP Tool into OpenAI/LangChain-compatible dict schema."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema,
            },
        }

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any], session_key: str) -> Any:
        """
        Execute a tool by name, routing it to the correct in-process server.

        Appends the execution trace to the session log.
        """
        server_type = self._tool_to_server.get(tool_name)
        if not server_type:
            raise ValueError(f"Unknown tool: {tool_name}")

        mcp_instance = self.gmail_mcp if server_type == "gmail" else self.analysis_mcp
        logger.info(
            "MCPRegistry: executing '%s' on %s server (session=%s)",
            tool_name,
            server_type,
            session_key,
        )

        async with Client(mcp_instance) as client:
            result = await client.call_tool(tool_name, arguments)

            if result.is_error:
                error_text = ""
                if result.content:
                    error_text = getattr(result.content[0], "text", str(result.content[0]))
                logger.error("MCP tool '%s' returned error: %s", tool_name, error_text)
                # Keep trace but indicate failure
                error_data = {"status": "failed", "error": error_text}
                add_trace_entry(session_key, tool_name, arguments, error_data)
                raise RuntimeError(f"MCP tool '{tool_name}' failed: {error_text}")

            data = result.data
            if not isinstance(data, dict):
                data = {"result": data, "status": "done"}

            # Log result in trace
            add_trace_entry(session_key, tool_name, arguments, data)
            return data
