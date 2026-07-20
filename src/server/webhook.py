"""
server/webhook.py — Gmail Pub/Sub push notification receiver + SSE live feed.

Endpoints:
  GET  /               → live monitoring dashboard
  GET  /health         → liveness check
  GET  /status         → full diagnostic JSON
  GET  /events         → Server-Sent Events stream
  POST /webhook/gmail  → receives Pub/Sub push notifications from Google
  POST /test/simulate  → injects a fake email to test the pipeline

Run:
    python -m src.server.webhook
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from fastapi.responses import HTMLResponse, StreamingResponse  # type: ignore
import uvicorn  # type: ignore

from src.core.config import (
    API_HOST, API_PORT, DEBUG, DEFAULT_REPLY_TONE, WEBHOOK_PUBLIC_URL,
    GMAIL_ADDRESS, PUBSUB_TOPIC, GCP_PROJECT_ID,
    GMAIL_CREDENTIALS_FILE, GMAIL_TOKEN_FILE,
    SIM_MESSAGE_ID, SIM_THREAD_ID, SIM_FALLBACK_RECIPIENT,
)

logger = logging.getLogger(__name__)

# ── Clear proxy env vars injected by pyngrok ──────────────────────────────────
for _var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_var, None)

# Force Gmail service to rebuild with proxy-free transport
try:
    from src.services.gmail.auth import reset_service
    from src.services.gmail.transport import _purge_proxy_env
    _purge_proxy_env()
    reset_service()
except Exception:
    pass

# ── Pre-load the MCP server so it's ready before first request ────────────────
try:
    from src.services.gmail.mcp_server import mcp as _gmail_mcp_server  # noqa: F401
    logger.debug("Gmail MCP server loaded")
except Exception as _mcp_exc:
    logger.warning("Gmail MCP server failed to pre-load: %s", _mcp_exc)

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Mail Analyzer Agent",
    description="Event-driven Gmail security monitor powered by LangGraph.",
    version="2.0.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── SSE clients ───────────────────────────────────────────────────────────────
_sse_clients: list[queue.Queue] = []
_sse_lock = threading.Lock()

# ── Deduplication ─────────────────────────────────────────────────────────────
_last_history_id: str = ""
_processed_message_ids: set[str] = set()
_processing_lock = threading.Lock()

# dashboard lives at project_root/dashboard/index.html
_PROJECT_ROOT   = Path(__file__).resolve().parent.parent.parent
_DASHBOARD_PATH = _PROJECT_ROOT / "dashboard" / "index.html"
_SECRETS_DIR    = _PROJECT_ROOT / "secrets"


def _broadcast(event_type: str, data: Any) -> None:
    payload = json.dumps({
        "type": event_type,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "data": data,
    }, default=str)
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)


def _process_message(message_id: str, thread_id: str, history_id: str) -> None:
    from src.services.gmail.fetcher import fetch_email
    from src.services.gmail.transport import _purge_proxy_env
    from src.agent.orchestrator import run_email_agent

    with _processing_lock:
        if message_id in _processed_message_ids:
            logger.info("Skipping already-processed message_id=%s", message_id)
            return
        _processed_message_ids.add(message_id)
        if len(_processed_message_ids) > 200:
            _processed_message_ids.discard(next(iter(_processed_message_ids)))

    _purge_proxy_env()
    logger.info("Processing message_id=%s thread_id=%s", message_id, thread_id)
    _broadcast("processing_started", {"message_id": message_id})

    try:
        raw_email = fetch_email(message_id)
        _broadcast("email_fetched", {
            "message_id": message_id,
            "subject":    raw_email.get("subject", ""),
            "sender":     raw_email.get("sender", ""),
        })
        report = run_email_agent(
            email=raw_email,
            gmail_message_id=message_id,
            gmail_thread_id=thread_id,
            history_id=history_id,
            reply_tone=DEFAULT_REPLY_TONE,
        )
        _broadcast("analysis_complete", report)
        logger.info("Done | id=%s rec='%s' risk=%d", message_id,
            report.get("decision", {}).get("recommendation", ""),
            report.get("security", {}).get("risk_score", 0))
    except Exception as exc:
        logger.exception("Processing failed for message_id=%s: %s", message_id, exc)
        _broadcast("processing_error", {"message_id": message_id, "error": str(exc)})


def _fetch_latest_message(email_address: str) -> None:
    from src.services.gmail.transport import _purge_proxy_env
    from src.services.gmail.auth import get_gmail_service
    _purge_proxy_env()
    try:
        service  = get_gmail_service()
        result   = service.users().messages().list(userId="me", labelIds=["INBOX"], maxResults=1).execute()
        messages = result.get("messages", [])
        if not messages:
            logger.info("Fallback fetch: no messages in inbox")
            return
        msg = messages[0]
        _process_message(msg["id"], msg.get("threadId", ""), "fallback")
    except Exception as exc:
        logger.exception("Fallback message fetch failed: %s", exc)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    if _DASHBOARD_PATH.exists():
        return HTMLResponse(
            content=_DASHBOARD_PATH.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
        )
    return HTMLResponse(content="<h1>Dashboard not found</h1><p>Expected: dashboard/index.html</p>", status_code=404)


@app.get("/health")
def health_check():
    return {
        "status":            "ok",
        "webhook_url":       f"{WEBHOOK_PUBLIC_URL}/webhook/gmail",
        "connected_clients": len(_sse_clients),
        "last_history_id":   _last_history_id or "none",
    }


@app.get("/status")
def status_check():
    creds_path = _SECRETS_DIR / GMAIL_CREDENTIALS_FILE
    token_path = _SECRETS_DIR / GMAIL_TOKEN_FILE
    issues = []
    if not GMAIL_ADDRESS:              issues.append("GMAIL_ADDRESS not set in .env")
    if not PUBSUB_TOPIC:               issues.append("PUBSUB_TOPIC not set in .env")
    if not GCP_PROJECT_ID:             issues.append("GCP_PROJECT_ID not set in .env")
    if not WEBHOOK_PUBLIC_URL:         issues.append("WEBHOOK_PUBLIC_URL not set in .env")
    if not creds_path.exists():        issues.append(f"credentials.json not found in secrets/")
    if not token_path.exists():        issues.append("token.json missing — run: python -m src.services.gmail.watcher")
    return {
        "status": "ready" if not issues else "misconfigured",
        "config": {
            "gmail_address":      GMAIL_ADDRESS,
            "pubsub_topic":       PUBSUB_TOPIC,
            "gcp_project_id":     GCP_PROJECT_ID,
            "webhook_url":        f"{WEBHOOK_PUBLIC_URL}/webhook/gmail",
            "credentials_exists": creds_path.exists(),
            "token_exists":       token_path.exists(),
            "sse_clients":        len(_sse_clients),
            "processed_messages": len(_processed_message_ids),
        },
        "issues": issues,
    }


@app.get("/events")
async def sse_stream(request: Request):
    client_queue: queue.Queue = queue.Queue(maxsize=100)
    with _sse_lock:
        _sse_clients.append(client_queue)
    logger.info("SSE client connected (total=%d)", len(_sse_clients))

    async def event_generator():
        try:
            yield "data: " + json.dumps({"type": "connected", "timestamp": datetime.utcnow().isoformat() + "Z"}) + "\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = client_queue.get(timeout=0.3)
                    yield f"data: {payload}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"
                    await asyncio.sleep(20)
        except asyncio.CancelledError:
            # Normal during server shutdown — SSE connections are cancelled cleanly
            pass
        finally:
            with _sse_lock:
                if client_queue in _sse_clients:
                    _sse_clients.remove(client_queue)
            logger.info("SSE client disconnected (total=%d)", len(_sse_clients))

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/webhook/gmail")
async def gmail_webhook(request: Request) -> Response:
    global _last_history_id

    raw_body = await request.body()
    logger.info("Webhook POST | length=%d | body=%s", len(raw_body),
                raw_body[:300].decode("utf-8", errors="replace"))

    try:
        body = json.loads(raw_body)
    except Exception:
        return Response(status_code=204)

    encoded_data = body.get("message", {}).get("data", "")
    if not encoded_data:
        return Response(status_code=204)

    try:
        notification = json.loads(base64.b64decode(encoded_data).decode("utf-8"))
    except Exception as exc:
        logger.warning("Webhook: could not decode data: %s", exc)
        return Response(status_code=204)

    history_id:    str = str(notification.get("historyId", ""))
    email_address: str = notification.get("emailAddress", "")
    logger.info("Pub/Sub | emailAddress=%s historyId=%s", email_address, history_id)

    if not history_id:
        return Response(status_code=200)

    with _processing_lock:
        if history_id == _last_history_id:
            logger.info("Skipping duplicate historyId=%s", history_id)
            return Response(status_code=200)
        prev_history_id  = _last_history_id
        _last_history_id = history_id

    def _background():
        from src.services.gmail.watcher import get_history
        from src.services.gmail.transport import _purge_proxy_env
        _purge_proxy_env()
        try:
            start_id     = prev_history_id or history_id
            new_messages = get_history(start_id)
            if not new_messages:
                logger.info("No new INBOX messages (startHistoryId=%s)", start_id)
                _fetch_latest_message(email_address)
                return
            for msg in new_messages:
                msg_id    = msg.get("id", "")
                thread_id = msg.get("threadId", "")
                if msg_id:
                    _process_message(msg_id, thread_id, history_id)
        except Exception as exc:
            logger.exception("Background processing failed: %s", exc)
            _fetch_latest_message(email_address)

    threading.Thread(target=_background, daemon=True).start()
    return Response(status_code=200)


@app.post("/test/simulate")
async def simulate_email():
    """Inject a fake phishing email to test the pipeline end-to-end."""
    from src.agent.orchestrator import run_email_agent

    fake_email = {
        "sender":     "Security Team <security@paypa1-alert.com>",
        "recipients": [GMAIL_ADDRESS or SIM_FALLBACK_RECIPIENT],
        "subject":    "URGENT: Your account has been suspended",
        "body_text": (
            "Dear Customer,\n\nWe detected suspicious activity on your account. "
            "Click below to verify:\nhttp://paypa1-alert.com/verify?token=abc123\n\n"
            "Failure to verify within 24 hours will result in permanent suspension.\n\nPayPal Security Team"
        ),
        "body_html": "",
        "attachments": [{"filename": "invoice.pdf.exe", "size_bytes": 512000}],
        "urls":    ["http://paypa1-alert.com/verify?token=abc123"],
        "headers": {"From": "security@paypa1-alert.com", "Reply-To": "harvest@scam.ru"},
        "metadata": {"source": "simulate_endpoint"},
    }

    def _run():
        try:
            _broadcast("processing_started", {"message_id": SIM_MESSAGE_ID})
            _broadcast("email_fetched", {"message_id": SIM_MESSAGE_ID,
                "subject": fake_email["subject"], "sender": fake_email["sender"]})
            report = run_email_agent(email=fake_email, gmail_message_id=SIM_MESSAGE_ID,
                                     gmail_thread_id=SIM_THREAD_ID, history_id="0")
            _broadcast("analysis_complete", report)
            logger.info("Simulation done — rec='%s' risk=%d",
                report.get("decision", {}).get("recommendation", ""),
                report.get("security", {}).get("risk_score", 0))
        except Exception as exc:
            logger.exception("Simulation failed: %s", exc)
            _broadcast("processing_error", {"message_id": SIM_MESSAGE_ID, "error": str(exc)})

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "simulation started", "dashboard": f"http://127.0.0.1:{API_PORT}"}


# ── Entry point ───────────────────────────────────────────────────────────────

import signal
import sys

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG if DEBUG else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info("Server     → http://%s:%d", API_HOST, API_PORT)
    logger.info("Dashboard  → http://127.0.0.1:%d/", API_PORT)
    logger.info("Pub/Sub    → %s/webhook/gmail", WEBHOOK_PUBLIC_URL or "(not set)")

    # ── Run uvicorn — let it handle SIGINT/SIGTERM natively ──────────────────
    # Do NOT install custom signal handlers — uvicorn's capture_signals()
    # manages Ctrl+C internally. Any custom handler conflicts with it on
    # Windows and causes restart loops.
    config = uvicorn.Config(
        app="src.server.webhook:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Server stopped cleanly.")
