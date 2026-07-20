"""
services/gmail/watcher.py — Gmail Watch API setup and renewal.

Run:
    python -m src.services.gmail.watcher
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def setup_watch() -> dict:
    """Register a Gmail push notification watch on the INBOX."""
    from src.core.config import PUBSUB_TOPIC, GMAIL_ADDRESS
    from src.services.gmail.auth import get_gmail_service
    from src.services.gmail.transport import _purge_proxy_env
    _purge_proxy_env()

    if not PUBSUB_TOPIC:
        raise ValueError(
            "PUBSUB_TOPIC is not set in .env.\n"
            "Create a Pub/Sub topic in Google Cloud Console and set:\n"
            "  PUBSUB_TOPIC=projects/YOUR_PROJECT/topics/YOUR_TOPIC"
        )

    service  = get_gmail_service()
    response = service.users().watch(userId="me", body={
        "labelIds": ["INBOX"],
        "topicName": PUBSUB_TOPIC,
        "labelFilterBehavior": "INCLUDE",
    }).execute()

    expiry_ms = int(response.get("expiration", 0))
    expiry_dt = datetime.fromtimestamp(expiry_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    logger.info("Gmail watch registered for %s | historyId=%s | expires=%s",
                GMAIL_ADDRESS, response.get("historyId"), expiry_dt)

    print(f"\n{'='*55}")
    print(f"  Gmail Watch registered")
    print(f"  Account   : {GMAIL_ADDRESS}")
    print(f"  historyId : {response.get('historyId')}")
    print(f"  Expires   : {expiry_dt}")
    print(f"  Topic     : {PUBSUB_TOPIC}")
    print(f"{'='*55}\n")

    return response


def stop_watch() -> None:
    """Stop the Gmail push notification watch."""
    from src.services.gmail.auth import get_gmail_service
    from src.core.config import GMAIL_ADDRESS
    get_gmail_service().users().stop(userId="me").execute()
    logger.info("Gmail watch stopped for %s", GMAIL_ADDRESS)
    print("Gmail watch stopped.")


def get_history(start_history_id: str) -> list[dict]:
    """Fetch messages added to INBOX since start_history_id."""
    from src.services.gmail.auth import get_gmail_service
    from src.services.gmail.transport import _purge_proxy_env
    _purge_proxy_env()
    service = get_gmail_service()
    messages_added = []

    try:
        response = service.users().history().list(
            userId="me",
            startHistoryId=start_history_id,
            historyTypes=["messageAdded"],
            labelId="INBOX",
        ).execute()

        for record in response.get("history", []):
            for msg_added in record.get("messagesAdded", []):
                messages_added.append(msg_added.get("message", {}))

        logger.info("History since %s: %d new messages", start_history_id, len(messages_added))
    except Exception as exc:
        logger.warning("History fetch failed (startHistoryId=%s): %s — will use fallback",
                       start_history_id, exc)

    return messages_added


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    setup_watch()
