"""SerpAPI (Google Jobs) integration — the sourcing layer's outbound seam.

This module is the *only* place that talks to SerpAPI. It is deliberately
DB-agnostic: it returns raw SerpAPI result dicts (and a mapper into the
``JobCreate`` DTO), leaving persistence and scheduling to the task layer
(:mod:`app.tasks.sourcing_task`).

Hard requirements honoured here:

* **Strictly async** — all HTTP goes through :class:`httpx.AsyncClient`; there is
  no synchronous client or ``requests`` usage anywhere.
* **Resilient** — every network failure (timeout, 5xx/4xx, connection error) is
  logged and re-raised as :class:`SourcingError` so the caller can recover one
  query at a time without the whole scheduled run dying.
* **Token-based pagination** — Google deprecated the ``start`` offset for the
  Jobs engine, so we follow ``serpapi_pagination.next_page_token`` instead.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import httpx

from app.core.config import get_sourcing_settings
from app.core.logging import get_logger
from app.models.schemas.job import JobCreate

logger = get_logger(__name__)

# Non-empty fallbacks so the (min_length=1) DTO fields never fail validation on a
# sparse SerpAPI result.
_UNKNOWN = "Unknown"
_NO_DESCRIPTION = "No description provided."


class SourcingError(Exception):
    """A SerpAPI request failed (timeout, HTTP error, or connection error)."""


@contextlib.asynccontextmanager
async def _client_context(
    client: httpx.AsyncClient | None, timeout: float
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an HTTP client, owning it only if one was not injected.

    When the caller passes a shared ``client`` (the task does, so a single
    connection pool is reused across all queries) we must **not** close it here.
    Otherwise we open a short-lived client scoped to this call.
    """
    if client is not None:
        yield client
    else:
        async with httpx.AsyncClient(timeout=timeout) as owned:
            yield owned


async def fetch_jobs_from_google(
    query: str,
    location: str,
    *,
    client: httpx.AsyncClient | None = None,
    max_pages: int | None = None,
) -> list[dict]:
    """Query SerpAPI's Google Jobs engine and return its ``jobs_results``.

    Args:
        query: Job title / search query (SerpAPI ``q``).
        location: Geographic location (SerpAPI ``location``).
        client: Optional shared :class:`httpx.AsyncClient` (dependency injection).
            If omitted, a short-lived client is created for this call. Reusing one
            client across many queries avoids rebuilding a connection pool per call.
        max_pages: Maximum result pages to follow via ``next_page_token``.
            Defaults to ``SourcingSettings.pages_per_query``.

    Returns:
        The accumulated list of raw job result dicts across all fetched pages
        (empty if SerpAPI returned no jobs).

    Raises:
        SourcingError: On any timeout, HTTP status error, or connection error.
    """
    settings = get_sourcing_settings()
    if max_pages is None:
        max_pages = settings.pages_per_query

    base_params: dict[str, str] = {
        "engine": "google_jobs",
        "q": query,
        "location": location,
        "api_key": settings.serpapi_key,
    }

    results: list[dict] = []
    next_page_token: str | None = None
    pages_fetched = 0

    try:
        async with _client_context(
            client, settings.request_timeout_seconds
        ) as active:
            while pages_fetched < max_pages:
                params = dict(base_params)
                if next_page_token:
                    params["next_page_token"] = next_page_token

                response = await active.get(settings.serpapi_base_url, params=params)
                response.raise_for_status()
                data = response.json()

                page_jobs = data.get("jobs_results") or []
                results.extend(page_jobs)
                pages_fetched += 1

                pagination = data.get("serpapi_pagination") or {}
                next_page_token = pagination.get("next_page_token")
                # Stop when there is no further page or this page was empty.
                if not next_page_token or not page_jobs:
                    break
    except httpx.TimeoutException as exc:
        logger.error(
            "sourcing_request_timeout",
            extra={"query": query, "location": location, "error_type": type(exc).__name__},
        )
        raise SourcingError(f"SerpAPI request timed out for query {query!r}") from exc
    except httpx.HTTPStatusError as exc:
        logger.error(
            "sourcing_http_error",
            extra={
                "query": query,
                "location": location,
                "status_code": exc.response.status_code,
                "error_type": type(exc).__name__,
            },
        )
        raise SourcingError(
            f"SerpAPI returned HTTP {exc.response.status_code} for query {query!r}"
        ) from exc
    except httpx.RequestError as exc:
        logger.error(
            "sourcing_request_error",
            extra={"query": query, "location": location, "error_type": type(exc).__name__},
        )
        raise SourcingError(f"SerpAPI request failed for query {query!r}") from exc

    return results


def _extract_source_url(raw: dict, job_id: str) -> str:
    """Pick the most useful human-facing link for a posting.

    Prefers ``share_link``, then the first apply-option link, finally a synthetic
    ``google_jobs://<job_id>`` so the (min_length=1) DTO field is always populated.
    Note this URL is *not* the dedup key — ``source_job_id`` is — because apply
    links rotate.
    """
    share_link = raw.get("share_link")
    if share_link:
        return share_link[:2048]

    for option in raw.get("apply_options") or []:
        link = option.get("link")
        if link:
            return link[:2048]

    return f"google_jobs://{job_id}"[:2048]


def _to_job_create(raw: dict) -> JobCreate | None:
    """Map a SerpAPI Google Jobs result into a :class:`JobCreate`.

    Returns ``None`` (logged) if the result lacks a ``job_id``, which is the
    stable dedup key — without it we cannot safely deduplicate, so we skip it.
    """
    job_id = raw.get("job_id")
    if not job_id:
        logger.warning(
            "sourcing_result_missing_job_id",
            extra={"title": raw.get("title"), "company": raw.get("company_name")},
        )
        return None

    return JobCreate(
        company_name=(raw.get("company_name") or _UNKNOWN)[:255],
        job_title=(raw.get("title") or _UNKNOWN)[:255],
        description=raw.get("description") or _NO_DESCRIPTION,
        source_url=_extract_source_url(raw, job_id),
        source_job_id=job_id[:512],
    )
