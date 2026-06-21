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

from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import get_ai_settings


@lru_cache
def _get_rate_limiter() -> InMemoryRateLimiter:
    """Return the process-wide limiter shared by every Gemini client.

    All model tiers default to the same flash-lite id and therefore share one
    per-minute project quota, so a single limiter must bound their *combined*
    request rate — not one per ``(model, temperature)`` client. A token bucket
    sized to one token (no bursting) paces calls to a steady cadence, which is
    what keeps a batch (e.g. the sourcing pre-screen scoring 25 postings) under
    the free-tier RPM ceiling instead of firing them all at once and hitting 429.
    """
    rpm = get_ai_settings().gemini_requests_per_minute
    return InMemoryRateLimiter(
        requests_per_second=rpm / 60.0,
        check_every_n_seconds=0.1,
        max_bucket_size=1,
    )


@lru_cache
def get_llm(
    model: str | None = None, temperature: float | None = None
) -> ChatGoogleGenerativeAI:
    """Return a process-wide cached Gemini chat client.

    A separate client is cached per ``(model, temperature)`` pair so the pipeline
    can mix tiers — a cheap flash model for analytical/structured nodes and a
    pro model for text generation — without rebuilding the SDK on every call.
    Both arguments fall back to :class:`~app.core.config.AISettings` defaults
    (the flash-tier model and the analytical temperature) when omitted.

    The API key is passed explicitly from ``AISettings`` so the client does not
    silently depend on ambient ``GOOGLE_API_KEY`` / ``GEMINI_API_KEY`` env vars.
    """
    settings = get_ai_settings()
    return ChatGoogleGenerativeAI(
        model=model or settings.gemini_model,
        api_key=settings.gemini_api_key,
        temperature=settings.gemini_temperature if temperature is None else temperature,
        # Keep retries low: on a hard quota (free-tier limit=0) the client would
        # otherwise back off and retry for minutes before the node's except fires.
        max_retries=settings.gemini_max_retries,
        # Shared limiter so all tiers together stay under the per-minute quota.
        rate_limiter=_get_rate_limiter(),
    )
