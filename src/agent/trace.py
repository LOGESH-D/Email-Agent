"""
agent/trace.py — Simple, thread-safe session trace and email manager.

Tracks tools executed during a single email analyzer run, and caches the raw email
data so that analysis tools can fetch it directly by session key.
"""

from __future__ import annotations

import logging
from typing import Any
import threading

logger = logging.getLogger(__name__)

# Lock for thread-safe access to traces and emails
_trace_lock = threading.Lock()

# Maps a session key (message_id or thread_id) to a list of tool call details
_traces: dict[str, list[dict[str, Any]]] = {}

# Maps a session key (message_id or thread_id) to the parsed email data dictionary
_emails: dict[str, dict[str, Any]] = {}


def init_session_trace(message_id: str, thread_id: str, email_data: dict[str, Any] | None = None) -> None:
    """Initialize a new trace list and cache email data for both message_id and thread_id."""
    with _trace_lock:
        trace_list: list[dict[str, Any]] = []
        if message_id:
            _traces[message_id] = trace_list
            if email_data is not None:
                _emails[message_id] = email_data
            logger.debug("Trace initialized for message_id: %s", message_id)
        if thread_id:
            _traces[thread_id] = trace_list
            if email_data is not None:
                _emails[thread_id] = email_data
            logger.debug("Trace initialized for thread_id: %s", thread_id)


def get_trace(session_key: str) -> list[dict[str, Any]]:
    """Retrieve the trace list associated with the given session key."""
    with _trace_lock:
        trace = _traces.get(session_key, [])
        logger.debug("Trace lookup for key '%s' found %d entries", session_key, len(trace))
        return trace


def get_session_email(session_key: str) -> dict[str, Any] | None:
    """Retrieve the cached email data associated with the given session key."""
    with _trace_lock:
        return _emails.get(session_key)


def add_trace_entry(session_key: str, tool_name: str, arguments: dict[str, Any], result: Any) -> None:
    """Append a tool execution entry to the trace list for the given session key."""
    with _trace_lock:
        trace_list = _traces.get(session_key)
        if trace_list is not None:
            trace_list.append({
                "tool": tool_name,
                "arguments": arguments,
                "result": result,
            })
            logger.info("Trace entry added: tool=%s to session=%s", tool_name, session_key)
        else:
            logger.warning("Attempted to add trace entry to non-existent session key: %s", session_key)


def clear_session_trace(message_id: str, thread_id: str) -> None:
    """Remove references to the trace and email data to clean up memory."""
    with _trace_lock:
        if message_id:
            _traces.pop(message_id, None)
            _emails.pop(message_id, None)
        if thread_id:
            _traces.pop(thread_id, None)
            _emails.pop(thread_id, None)
        logger.debug("Trace and email data cleared for message_id=%s thread_id=%s", message_id, thread_id)
