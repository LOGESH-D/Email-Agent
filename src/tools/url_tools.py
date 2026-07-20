"""
URL analysis utilities.

Provides heuristic checks for:
  - HTTP vs HTTPS
  - Known URL shorteners
  - Suspicious keywords in URLs
  - Basic typosquatting patterns against a whitelist of trusted domains
  - Tracking parameters
  - URL expansion (follows redirects, no JS required)
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

# ── Known URL shorteners ────────────────────────────────────────────────────
SHORTENER_DOMAINS: set[str] = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly",
    "short.link", "rb.gy", "cutt.ly", "is.gd", "buff.ly",
    "dl.dropboxusercontent.com", "tiny.cc",
}

# ── Common tracking parameters ──────────────────────────────────────────────
TRACKING_PARAMS: set[str] = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid",
}


def expand_url(url: str, timeout: int = 5) -> str:
    """
    Follow redirects to find the final destination URL.
    Returns the original URL if expansion fails.
    """
    try:
        import requests  # type: ignore

        resp = requests.head(url, allow_redirects=True, timeout=timeout)
        return resp.url
    except Exception as exc:
        logger.debug("URL expansion failed for %s: %s", url, exc)
        return url


def analyze_url(url: str) -> dict:
    """
    Perform a full analysis of a single URL, using LLM for typosquatting & keyword detection.

    Returns a dict compatible with the URLAnalysis TypedDict.
    """
    reasons: list[str] = []

    try:
        parsed = urlparse(url)
    except Exception:
        return {
            "url": url,
            "is_https": False,
            "is_shortened": False,
            "domain": "",
            "suspicious": True,
            "reasons": ["Could not parse URL"],
            "final_url": None,
        }

    domain = parsed.netloc.lower()
    # Remove port if present
    domain = domain.split(":")[0]

    # ── HTTPS check ──────────────────────────────────────────────────────────
    is_https = parsed.scheme == "https"
    if not is_https:
        reasons.append("Uses HTTP (not encrypted)")

    # ── Shortened URL ────────────────────────────────────────────────────────
    is_shortened = domain in SHORTENER_DOMAINS
    if is_shortened:
        reasons.append(f"Known URL shortener: {domain}")

    # ── Tracking parameters ───────────────────────────────────────────────────
    params = parse_qs(parsed.query)
    tracking = [p for p in params if p.lower() in TRACKING_PARAMS]
    if tracking:
        reasons.append(f"Tracking parameters detected: {', '.join(tracking)}")

    # ── IP address as host (common in phishing) ───────────────────────────────
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", domain):
        reasons.append("URL uses raw IP address instead of domain name")

    # ── Attempt URL expansion if shortened ────────────────────────────────────
    final_url: str | None = None
    if is_shortened:
        expanded = expand_url(url)
        if expanded != url:
            final_url = expanded
            reasons.append(f"Expands to: {expanded}")

    # ── LLM-based phishing & typosquatting detection ──
    try:
        from src.core.utils import get_llm, safe_json_parse
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = get_llm()
        messages = [
            SystemMessage(content=(
                "You are an expert cybersecurity URL analyzer.\n"
                "Determine if the given URL is suspicious, phishing, typosquatted (mimicking well-known brands), "
                "or malicious in any other way. Check the domain structure and keywords.\n"
                "Return a JSON object in this format:\n"
                "{\n"
                "  \"suspicious\": true/false,\n"
                "  \"reasons\": [\"reason 1\", \"reason 2\"]\n"
                "}"
            )),
            HumanMessage(content=f"Analyze this URL: {url}"),
        ]
        llm_res = llm.invoke(messages).content
        parsed_res = safe_json_parse(llm_res)
        if parsed_res.get("suspicious"):
            reasons.extend(parsed_res.get("reasons", ["LLM flagged URL as suspicious"]))
    except Exception as exc:
        logger.warning("LLM URL analysis failed: %s", exc)

    suspicious = bool(reasons)

    return {
        "url": url,
        "is_https": is_https,
        "is_shortened": is_shortened,
        "domain": domain,
        "suspicious": suspicious,
        "reasons": reasons,
        "final_url": final_url,
    }
