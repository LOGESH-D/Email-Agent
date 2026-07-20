"""
core/utils.py — Shared utilities: LLM factory and JSON parser.
"""

from __future__ import annotations

import json
import logging
import re

from src.core.config import (
    GROQ_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY,
    MODEL_NAME, LLM_TEMPERATURE,
    GROQ_DEFAULT_MODEL, OPENAI_DEFAULT_MODEL,
    ANTHROPIC_DEFAULT_MODEL, OLLAMA_DEFAULT_MODEL,
)

logger = logging.getLogger(__name__)

_llm = None


def get_llm():
    """
    Return a configured LangChain chat model.

    Provider priority (first key found wins):
      1. GROQ_API_KEY       → ChatGroq
      2. OPENAI_API_KEY     → ChatOpenAI
      3. ANTHROPIC_API_KEY  → ChatAnthropic
      4. Ollama local       → ChatOllama (no key needed)
    """
    global _llm
    if _llm is not None:
        return _llm

    if GROQ_API_KEY:
        from langchain_groq import ChatGroq  # type: ignore
        model = MODEL_NAME or GROQ_DEFAULT_MODEL
        logger.info("LLM: ChatGroq | model=%s | temp=%s", model, LLM_TEMPERATURE)
        _llm = ChatGroq(api_key=GROQ_API_KEY, model=model, temperature=LLM_TEMPERATURE)
        return _llm

    if OPENAI_API_KEY:
        from langchain_openai import ChatOpenAI  # type: ignore
        model = MODEL_NAME or OPENAI_DEFAULT_MODEL
        logger.info("LLM: ChatOpenAI | model=%s | temp=%s", model, LLM_TEMPERATURE)
        _llm = ChatOpenAI(api_key=OPENAI_API_KEY, model=model, temperature=LLM_TEMPERATURE)
        return _llm

    if ANTHROPIC_API_KEY:
        from langchain_anthropic import ChatAnthropic  # type: ignore
        model = MODEL_NAME or ANTHROPIC_DEFAULT_MODEL
        logger.info("LLM: ChatAnthropic | model=%s | temp=%s", model, LLM_TEMPERATURE)
        _llm = ChatAnthropic(api_key=ANTHROPIC_API_KEY, model=model, temperature=LLM_TEMPERATURE)  # type: ignore
        return _llm

    try:
        from langchain_ollama import ChatOllama  # type: ignore
        model = MODEL_NAME or OLLAMA_DEFAULT_MODEL
        logger.info("LLM: ChatOllama | model=%s | temp=%s", model, LLM_TEMPERATURE)
        _llm = ChatOllama(model=model, temperature=LLM_TEMPERATURE)
        return _llm
    except ImportError:
        pass

    raise EnvironmentError(
        "No LLM provider configured. "
        "Add GROQ_API_KEY (or OPENAI_API_KEY / ANTHROPIC_API_KEY) to your .env file."
    )


def safe_json_parse(text: str) -> dict:
    """Parse JSON from LLM output that may be wrapped in markdown code fences."""
    stripped = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    match = re.search(r"(\{.*\}|\[.*\])", stripped, re.DOTALL)
    if match:
        stripped = match.group(0)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        logger.warning("JSON parse error: %s\nRaw text: %s", exc, text[:500])
        return {}
