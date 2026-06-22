"""Apify (LinkedIn Jobs) integration — the sourcing layer's outbound seam.

This module is the *only* place that talks to Apify. It is deliberately
DB-agnostic: it returns raw Apify dataset item dicts (and a mapper into the
``JobCreate`` DTO), leaving persistence and scheduling to the task layer
(:mod:`app.tasks.sourcing_task`).

Hard requirements honoured here:

* **apify-client only** — all Apify traffic goes through
  :class:`apify_client.ApifyClientAsync`. There is no hand-rolled HTTP to the
  Apify API anywhere (the client manages its own transport).
* **Cost-first** — an actor run spins up a billed container, so the caller makes
  exactly one run per profile (titles OR-joined into a single Boolean query) and
  we cap the actor's ``pages`` input. We do *not* loop per title.
* **Resilient** — any failure (bad token, actor error, missing dataset) is logged
  and re-raised as :class:`SourcingError` so the caller can recover one profile
  at a time without the whole scheduled run dying.
* **Long-running aware** — the actor typically takes 1-3 minutes; ``.call()``
  waits for completion (no client-side timeout) and we log start/finish so a slow
  run reads as progress, not a hang.
"""

from __future__ import annotations

from urllib.parse import urlencode

from apify_client import ApifyClientAsync

from app.core.config import get_sourcing_settings
from app.core.logging import get_logger
from app.models.schemas.job import JobCreate

logger = get_logger(__name__)

# Non-empty fallbacks so the (min_length=1) DTO fields never fail validation on a
# sparse Apify item.
_UNKNOWN = "Unknown"
_NO_DESCRIPTION = "No description provided."

# The curious_coder/linkedin-jobs-scraper actor is URL-driven: its required
# ``urls`` input is a list of LinkedIn job-search result pages, NOT a keyword +
# location pair. We synthesise the standard guest search URL from the query and
# location so the rest of the pipeline can keep speaking in (query, location).
_LINKEDIN_JOBS_SEARCH_URL = "https://www.linkedin.com/jobs/search/"
# LinkedIn returns ~25 jobs per result page; the actor caps total results with
# ``count`` (it has no ``pages`` input), so we translate the cost-bounding
# ``pages`` setting into an equivalent result count.
_RESULTS_PER_PAGE = 25

# LinkedIn's guest search only geo-filters reliably when the URL carries a numeric
# ``geoId``; the free-text ``location`` alone is matched loosely and frequently
# falls back to broad / US-centric results (the cause of "I set Israel but get
# US/Canada postings"). We map the locations we support to their LinkedIn geoId
# and attach it; unknown locations still send the text param (LinkedIn best-effort)
# and can be added here as the need arises.
_LINKEDIN_GEO_IDS: dict[str, str] = {
    "israel": "101620260",
    "united states": "103644278",
    "united states of america": "103644278",
    "usa": "103644278",
    "us": "103644278",
    "canada": "101174742",
    "united kingdom": "101165590",
    "uk": "101165590",
    "germany": "101282230",
    "netherlands": "102890719",
}


def _resolve_geo_id(location: str) -> str | None:
    """Map a location string to its LinkedIn ``geoId``, or ``None`` if unknown.

    Matches the whole string first, then the last comma-separated component, so
    ``"Tel Aviv-Yafo, Israel"`` resolves via ``"israel"``. An unknown location
    returns ``None`` and the caller sends only the free-text ``location``.
    """
    key = location.strip().lower()
    if key in _LINKEDIN_GEO_IDS:
        return _LINKEDIN_GEO_IDS[key]
    tail = key.rsplit(",", 1)[-1].strip()
    return _LINKEDIN_GEO_IDS.get(tail)


def _linkedin_search_url(query: str, location: str) -> str:
    """Build a LinkedIn guest job-search URL from a Boolean query + location.

    ``urlencode`` percent-encodes the quotes/OR in the Boolean query and any
    spaces in the location, producing the ``urls`` entry the actor requires, e.g.
    ``…/jobs/search/?keywords=%22AI+Engineer%22&location=Israel&geoId=101620260``.
    A resolvable ``geoId`` is appended so LinkedIn actually restricts results to
    that region (see ``_LINKEDIN_GEO_IDS``).
    """
    params = {"keywords": query, "location": location}
    geo_id = _resolve_geo_id(location)
    if geo_id:
        params["geoId"] = geo_id
    return f"{_LINKEDIN_JOBS_SEARCH_URL}?{urlencode(params)}"


class SourcingError(Exception):
    """An Apify actor run failed (bad token, actor error, or missing dataset)."""


def _first(raw: dict, *keys: str) -> str | None:
    """Return the first non-empty value among ``keys``, or ``None``.

    The curious_coder actor renamed fields across builds (e.g. ``companyName`` vs
    legacy ``company``), so each mapped field reads new-then-old. Empty strings
    count as absent, so a blank value never shadows a populated alias — or lands
    in a NOT-NULL/``min_length`` column.
    """
    for key in keys:
        value = raw.get(key)
        if value:
            return value
    return None


def _truncate(value: str | None, limit: int) -> str | None:
    """Clamp an optional string to ``limit`` chars, preserving ``None``."""
    return value[:limit] if value else None


def _coerce_int(value: object) -> int | None:
    """Best-effort coerce an Apify value to a non-negative ``int``, else ``None``.

    ``companyEmployeesCount`` usually arrives as an int but a build may emit it
    as a numeric string; anything non-numeric or negative maps to ``None`` so a
    junk value never reaches the column.
    """
    if value is None:
        return None
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced >= 0 else None


def _run_field(run: object, attr: str, alias: str) -> object:
    """Read a field off an actor run regardless of apify-client major version.

    apify-client >=3 returns a Pydantic ``Run`` model (attribute access, e.g.
    ``run.default_dataset_id``); older 1.x/2.x returned a plain dict keyed by the
    camelCase API alias (``run["defaultDatasetId"]``). Support both so a version
    bump in either direction doesn't break sourcing.
    """
    if run is None:
        return None
    if hasattr(run, attr):
        return getattr(run, attr)
    if isinstance(run, dict):
        return run.get(alias)
    return None


async def fetch_jobs_from_apify(
    query: str,
    location: str,
    *,
    client: ApifyClientAsync | None = None,
) -> list[dict]:
    """Run the LinkedIn Jobs Apify actor once and return its dataset items.

    Args:
        query: Boolean search query (e.g. ``'"AI Engineer" OR "ML Engineer"'``).
            The whole profile's titles are OR-joined into this single string so
            one container run covers every title — see the cost note above.
        location: Geographic location passed to the actor.
        client: Optional shared :class:`ApifyClientAsync` (dependency injection).
            If omitted, one is created for this call from ``APIFY_TOKEN``. Reusing
            one client across profiles avoids rebuilding it per run.

    Returns:
        The actor's dataset items as raw dicts (empty if the actor returned none).

    Raises:
        SourcingError: On any failure starting the actor, waiting for it, or
            reading its dataset.
    """
    settings = get_sourcing_settings()
    if client is None:
        client = ApifyClientAsync(token=settings.apify_token)

    run_input = {
        # The actor is URL-driven; ``urls`` is its only required input.
        "urls": [_linkedin_search_url(query, location)],
        # No ``pages`` input on this actor — bound results via ``count`` instead.
        "count": settings.pages * _RESULTS_PER_PAGE,
        # Scrape the per-company profile so items carry company metadata
        # (``companyEmployeesCount`` -> employee_count on the card). This costs
        # extra container time per run but is the only source of the headcount.
        "scrapeCompany": True,
    }

    logger.info(
        "sourcing_actor_started",
        extra={
            "actor": settings.apify_actor_id,
            "query": query,
            "location": location,
            "count": run_input["count"],
        },
    )
    try:
        # .call() blocks until the run finishes — the actor can take 1-3 minutes,
        # which is normal; there is no client-side timeout so the task never dies
        # waiting on a healthy-but-slow run.
        run = await client.actor(settings.apify_actor_id).call(run_input=run_input)
        dataset_id = _run_field(run, "default_dataset_id", "defaultDatasetId")
        if not dataset_id:
            raise SourcingError(
                f"Apify actor returned no dataset for query {query!r}"
            )

        dataset = await client.dataset(dataset_id).list_items()
        items = dataset.items
    except SourcingError:
        raise
    except Exception as exc:  # noqa: BLE001 - any actor/transport failure is non-fatal
        logger.error(
            "sourcing_actor_failed",
            extra={
                "actor": settings.apify_actor_id,
                "query": query,
                "location": location,
                "error_type": type(exc).__name__,
            },
        )
        raise SourcingError(
            f"Apify actor run failed for query {query!r}: {exc}"
        ) from exc

    logger.info(
        "sourcing_actor_finished",
        extra={
            "actor": settings.apify_actor_id,
            "query": query,
            "location": location,
            "status": str(_run_field(run, "status", "status")),
            "fetched": len(items),
        },
    )
    return items


def _to_job_create(raw: dict) -> JobCreate | None:
    """Map a raw Apify LinkedIn-Jobs item into a :class:`JobCreate`.

    Field names are read with fallbacks because the curious_coder actor changed
    its output schema across builds: the current build emits ``id`` / ``title`` /
    ``companyName`` / ``link`` / ``descriptionText``, while older builds (and the
    test fixtures) used ``job_id`` / ``job_title`` / ``company`` / ``job_url`` /
    ``description``. We accept either so a build bump never silently drops every
    posting.

    Returns ``None`` (logged) if the item lacks any job id, which is the stable
    dedup key — without it we cannot safely deduplicate, so we skip it.
    """
    raw_job_id = _first(raw, "id", "job_id")
    if not raw_job_id:
        logger.warning(
            "sourcing_result_missing_job_id",
            extra={
                "job_title": _first(raw, "title", "job_title"),
                "company": _first(raw, "companyName", "company"),
            },
        )
        return None

    # LinkedIn ids may arrive as ints; coerce to the str the dedup key expects.
    job_id = str(raw_job_id)
    # The job URL should always be present, but the (min_length=1) DTO field must
    # never be empty, so fall back to a synthetic, dedup-stable URL.
    source_url = (_first(raw, "link", "job_url") or f"apify://{job_id}")[:2048]

    return JobCreate(
        company_name=_truncate(_first(raw, "companyName", "company") or _UNKNOWN, 255),
        job_title=_truncate(_first(raw, "title", "job_title") or _UNKNOWN, 255),
        # Prefer the plain-text description (better for the LLM) over the HTML one.
        description=_first(raw, "descriptionText", "description") or _NO_DESCRIPTION,
        source_url=source_url,
        source_job_id=job_id[:512],
        # Rich, optional LinkedIn metadata — absent/blank values map to NULL.
        location=_truncate(_first(raw, "location"), 255),
        employment_type=_truncate(_first(raw, "employmentType"), 100),
        seniority_level=_truncate(_first(raw, "seniorityLevel"), 100),
        salary=_truncate(_first(raw, "salary"), 255),
        # The employer's own website — used downstream for an accurate Hunter.io
        # recruiter lookup.
        company_website=_truncate(_first(raw, "companyWebsite"), 255),
        # Company headcount — only present when ``scrapeCompany`` is enabled.
        employee_count=_coerce_int(raw.get("companyEmployeesCount")),
        # The company's LinkedIn page — only present when ``scrapeCompany`` is on.
        company_linkedin_url=_truncate(
            _first(raw, "companyLinkedinUrl", "companyUrl"), 512
        ),
    )
