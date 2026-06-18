"""Gemini LLM client factory for the LangGraph matching pipeline.

This module is the single place that constructs the official
``langchain-google-genai`` ``ChatGoogleGenerativeAI`` client. Nodes import
:func:`get_llm` rather than instantiating the SDK themselves so that:

* configuration (model id, API key, temperature) is read exactly once, and
* the underlying client — which holds connection/transport state — is reused
  across the whole process instead of being rebuilt on every node invocation.

The client is cached with :func:`functools.lru_cache`; tests can reset it via
``get_llm.cache_clear()``.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import get_ai_settings


@lru_cache
def get_llm() -> ChatGoogleGenerativeAI:
    """Return a process-wide cached Gemini chat client.

    The API key is passed explicitly from :class:`~app.core.config.AISettings`
    so the client does not silently depend on ambient ``GOOGLE_API_KEY`` /
    ``GEMINI_API_KEY`` environment variables.
    """
    settings = get_ai_settings()
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        api_key=settings.gemini_api_key,
        temperature=settings.gemini_temperature,
    )
