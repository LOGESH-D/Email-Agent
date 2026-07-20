"""
core/config.py — Central configuration loader.

Reads all settings from the .env file (via python-dotenv) and exposes
them as typed constants. Every other module imports from here instead
of calling os.getenv() directly.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv  # type: ignore

# .env lives at the project root (three levels up: src/core/ → src/ → root)
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)

# ── LLM Provider Keys ─────────────────────────────────────────────────────────
GROQ_API_KEY: str       = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY: str     = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY: str  = os.getenv("ANTHROPIC_API_KEY", "")

# ── Model Settings ────────────────────────────────────────────────────────────
MODEL_NAME: str         = os.getenv("MODEL_NAME", "meta-llama/llama-4-scout-17b-16e-instruct")
LLM_TEMPERATURE: float  = float(os.getenv("LLM_TEMPERATURE", "0"))

# ── Reply Settings ────────────────────────────────────────────────────────────
DEFAULT_REPLY_TONE: str    = os.getenv("DEFAULT_REPLY_TONE", "professional")
REPLY_RISK_THRESHOLD: int  = int(os.getenv("REPLY_RISK_THRESHOLD", "40"))

# ── Web Search ────────────────────────────────────────────────────────────────
WEB_SEARCH_MAX_RESULTS: int = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))

# ── Gmail OAuth2 ──────────────────────────────────────────────────────────────
# credentials.json and token.json live in secrets/ at the project root
GMAIL_CREDENTIALS_FILE: str = os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
GMAIL_TOKEN_FILE: str       = os.getenv("GMAIL_TOKEN_FILE", "token.json")
GMAIL_ADDRESS: str          = os.getenv("GMAIL_ADDRESS", "")

# ── Google Cloud Pub/Sub ──────────────────────────────────────────────────────
PUBSUB_TOPIC: str    = os.getenv("PUBSUB_TOPIC", "")
GCP_PROJECT_ID: str  = os.getenv("GCP_PROJECT_ID", "")

# ── Webhook Server ────────────────────────────────────────────────────────────
API_HOST: str          = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int          = int(os.getenv("API_PORT", "8000"))
WEBHOOK_PUBLIC_URL: str = os.getenv("WEBHOOK_PUBLIC_URL", "")
DEBUG: bool            = os.getenv("DEBUG", "false").lower() == "true"

# ── Auto-action Thresholds ────────────────────────────────────────────────────
AUTO_SPAM_THRESHOLD: int   = int(os.getenv("AUTO_SPAM_THRESHOLD", "75"))
AUTO_DELETE_THRESHOLD: int = int(os.getenv("AUTO_DELETE_THRESHOLD", "90"))

# ── Gmail Label Names ─────────────────────────────────────────────────────────
LABEL_NEEDS_REVIEW: str      = os.getenv("LABEL_NEEDS_REVIEW", "Needs Review")
LABEL_PHISHING_DETECTED: str = os.getenv("LABEL_PHISHING_DETECTED", "Phishing Detected")

# ── LLM Provider Default Models ───────────────────────────────────────────────
GROQ_DEFAULT_MODEL: str      = os.getenv("GROQ_DEFAULT_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
OPENAI_DEFAULT_MODEL: str    = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")
ANTHROPIC_DEFAULT_MODEL: str = os.getenv("ANTHROPIC_DEFAULT_MODEL", "claude-3-haiku-20240307")
OLLAMA_DEFAULT_MODEL: str    = os.getenv("OLLAMA_DEFAULT_MODEL", "llama3")

# ── Simulation ────────────────────────────────────────────────────────────────
SIM_MESSAGE_ID: str          = os.getenv("SIM_MESSAGE_ID", "sim-001")
SIM_THREAD_ID: str           = os.getenv("SIM_THREAD_ID", "sim-thread-001")
SIM_FALLBACK_RECIPIENT: str  = os.getenv("SIM_FALLBACK_RECIPIENT", "you@gmail.com")
