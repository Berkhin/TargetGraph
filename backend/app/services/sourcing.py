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


def _linkedin_search_url(query: str, location: str) -> str:
    """Build a LinkedIn guest job-search URL from a Boolean query + location.

    ``urlencode`` percent-encodes the quotes/OR in the Boolean query and any
    spaces in the location, producing the ``urls`` entry the actor requires, e.g.
    ``https://www.linkedin.com/jobs/search/?keywords=%22AI+Engineer%22&location=Israel``.
    """
    return f"{_LINKEDIN_JOBS_SEARCH_URL}?{urlencode({'keywords': query, 'location': location})}"


class SourcingError(Exception):
    """An Apify actor run failed (bad token, actor error, or missing dataset)."""


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
        # Skip per-company profile scraping: company_name is already on the job
        # listing, and the extra fetch costs more container time for data we drop.
        "scrapeCompany": False,
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
    job_id = raw.get("id") or raw.get("job_id")
    if not job_id:
        logger.warning(
            "sourcing_result_missing_job_id",
            extra={
                "job_title": raw.get("title") or raw.get("job_title"),
                "company": raw.get("companyName") or raw.get("company"),
            },
        )
        return None

    job_id = str(job_id)
    # The job URL should always be present, but the (min_length=1) DTO field must
    # never be empty, so fall back to a synthetic, dedup-stable URL.
    source_url = (raw.get("link") or raw.get("job_url") or f"apify://{job_id}")[:2048]

    # Rich, optional metadata from the LinkedIn jobs scraper. .get() returns None
    # when the key is absent, so a sparse item never raises here.
    location = raw.get("location")
    employment_type = raw.get("employmentType")
    seniority_level = raw.get("seniorityLevel")
    salary_raw = raw.get("salary")
    salary = salary_raw if salary_raw else None  # guard against empty string ""
    # The employer's own website — used downstream for an accurate Hunter.io
    # recruiter lookup. Empty string guarded so we store NULL, not "".
    company_website = raw.get("companyWebsite") or None

    # Prefer the plain-text description (better for the LLM) over the HTML one.
    description = (
        raw.get("descriptionText") or raw.get("description") or _NO_DESCRIPTION
    )

    return JobCreate(
        company_name=(raw.get("companyName") or raw.get("company") or _UNKNOWN)[:255],
        job_title=(raw.get("title") or raw.get("job_title") or _UNKNOWN)[:255],
        description=description,
        source_url=source_url,
        source_job_id=job_id[:512],
        location=location[:255] if location else None,
        employment_type=employment_type[:100] if employment_type else None,
        seniority_level=seniority_level[:100] if seniority_level else None,
        salary=salary[:255] if salary else None,
        company_website=company_website[:255] if company_website else None,
    )
