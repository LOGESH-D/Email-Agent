"""
services/gmail/auth.py — Gmail OAuth2 authentication using proxy-free requests transport.

credentials.json and token.json are read from the secrets/ folder at the project root.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.core.config import GMAIL_CREDENTIALS_FILE, GMAIL_TOKEN_FILE
from src.services.gmail.transport import _purge_proxy_env, RequestsHttpTransport, build_no_proxy_http

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

# secrets/ lives at the project root (four levels up: src/services/gmail/ → src/services/ → src/ → root)
_PROJECT_ROOT     = Path(__file__).resolve().parent.parent.parent.parent
_SECRETS_DIR      = _PROJECT_ROOT / "secrets"
_CREDENTIALS_PATH = _SECRETS_DIR / GMAIL_CREDENTIALS_FILE
_TOKEN_PATH       = _SECRETS_DIR / GMAIL_TOKEN_FILE

_gmail_service = None


def _get_credentials():
    """Load, refresh, or obtain fresh OAuth2 credentials."""
    from google.oauth2.credentials import Credentials           # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow      # type: ignore
    from google.auth.transport.requests import Request          # type: ignore
    import requests                                             # type: ignore

    _purge_proxy_env()

    creds = None
    if _TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Gmail auth: refreshing token")
            s = requests.Session()
            s.trust_env = False
            s.proxies   = {"http": "", "https": ""}
            creds.refresh(Request(session=s))
        else:
            logger.info("Gmail auth: starting OAuth2 flow")
            if not _CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"credentials.json not found: {_CREDENTIALS_PATH}\n"
                    "Download from Google Cloud Console → APIs & Services → Credentials\n"
                    "and place it in the secrets/ folder."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(_CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)

        _TOKEN_PATH.write_text(creds.to_json())
        logger.info("Gmail auth: token saved → %s", _TOKEN_PATH)

    return creds


def get_gmail_service():
    """Return an authenticated Gmail API service. Cached for the process lifetime."""
    global _gmail_service
    if _gmail_service is not None:
        return _gmail_service

    _purge_proxy_env()

    from googleapiclient.discovery import build  # type: ignore

    creds              = _get_credentials()
    authed_session     = build_no_proxy_http(creds)
    requests_transport = RequestsHttpTransport(authed_session)

    _gmail_service = build("gmail", "v1", http=requests_transport, cache_discovery=False)
    logger.info("Gmail auth: service ready (proxy-free transport)")
    return _gmail_service


def reset_service() -> None:
    """Force a fresh service build on next call."""
    global _gmail_service
    _gmail_service = None
