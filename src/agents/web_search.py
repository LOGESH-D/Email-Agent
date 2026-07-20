"""Agent 7 — Web Search / Reputation Agent"""

from __future__ import annotations
import logging
from src.core.config import WEB_SEARCH_MAX_RESULTS
from src.core.state import EmailState
from src.tools.search import web_search, summarize_search_results

logger = logging.getLogger(__name__)


def search_reputation(state: EmailState) -> dict:
    sender = state.get("sender", "")
    domain = state.get("sender_domain", "")

    sender_results, domain_results = [], []

    if sender:
        query = (f'"{sender}" email scam phishing report '
                 f'site:reddit.com OR site:spamhaus.org OR site:mxtoolbox.com')
        logger.info("Web search: sender query → %s", query)
        sender_results = web_search(query, max_results=WEB_SEARCH_MAX_RESULTS)

    if domain:
        query = f'"{domain}" email domain reputation scam phishing blacklist'
        logger.info("Web search: domain query → %s", query)
        domain_results = web_search(query, max_results=WEB_SEARCH_MAX_RESULTS)

    sender_reputation = summarize_search_results(sender_results) if sender_results else "No results found."
    domain_reputation = summarize_search_results(domain_results) if domain_results else "No results found."

    logger.info("Web search: done sender=%s domain=%s", sender, domain)
    return {
        "sender_reputation":  sender_reputation,
        "domain_reputation":  domain_reputation,
        "web_search_summary": f"Sender ({sender}):\n{sender_reputation}\n\nDomain ({domain}):\n{domain_reputation}",
    }
