"""The periodic job-sourcing task driven by APScheduler.

This is the seam between the (DB-agnostic) SerpAPI service and persistence. Each
run reads every master profile's target titles + preferred location, queries
Google Jobs for each title, and persists postings that aren't already known
(deduped by ``source_job_id``) with status ``NEW`` for the AI matching pipeline
to pick up later.

Resilience notes (the scheduler must survive everything):

* The whole body is wrapped so an unexpected error is logged, never propagated —
  a thrown task would otherwise be swallowed by APScheduler and leave no trace.
* A failed query (:class:`SourcingError`) is counted and skipped; the run
  continues with the next title.
* **Transactional radius:** each query's postings are committed as their own
  batch, and every insert runs inside a SAVEPOINT. So a DB error (or a
  race-condition ``IntegrityError`` from a concurrent run inserting the same
  ``source_job_id``) discards only that one row — never the postings already
  committed earlier in the run.
* **Connection reuse:** one :class:`httpx.AsyncClient` is opened for the whole
  run and shared across every query, then closed once at the end.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.exc import IntegrityError

from app.core.config import get_sourcing_settings
from app.core.logging import get_logger
from app.db.database import AsyncSessionLocal
from app.repositories.job_repository import JobRepository
from app.repositories.profile_repository import ProfileRepository
from app.services.sourcing import SourcingError, _to_job_create, fetch_jobs_from_google

logger = get_logger(__name__)


def _resolve_location(preferences: dict[str, Any], default: str) -> str:
    """Pick a usable search location from a profile's preferences."""
    location = preferences.get("location") if preferences else None
    if isinstance(location, str) and location.strip():
        return location
    return default


async def run_sourcing_job(session_factory: Any = AsyncSessionLocal) -> None:
    """Fetch fresh postings for every profile's target titles and persist new ones.

    Args:
        session_factory: Async session factory (``async_sessionmaker``). Injectable
            so tests can pass a SQLite-backed factory.
    """
    settings = get_sourcing_settings()

    added = 0
    skipped = 0
    query_errors = 0
    profiles_processed = 0

    logger.info("sourcing_job_started")
    try:
        async with httpx.AsyncClient(
            timeout=settings.request_timeout_seconds
        ) as client:
            async with session_factory() as session:
                profile_repo = ProfileRepository(session)
                job_repo = JobRepository(session)

                profiles = await profile_repo.get_all_profiles()
                if not profiles:
                    logger.warning("sourcing_no_profiles")
                    return

                for profile in profiles:
                    titles = profile.target_titles or []
                    if not titles:
                        continue
                    profiles_processed += 1
                    location = _resolve_location(
                        profile.preferences, settings.default_location
                    )

                    for title in titles:
                        try:
                            raw_results = await fetch_jobs_from_google(
                                title, location, client=client
                            )
                        except SourcingError:
                            # Already logged in the service with full context.
                            query_errors += 1
                            continue

                        title_added = 0
                        title_skipped = 0
                        for raw in raw_results:
                            job_create = _to_job_create(raw)
                            if job_create is None or job_create.source_job_id is None:
                                continue

                            existing = await job_repo.get_by_source_job_id(
                                job_create.source_job_id
                            )
                            if existing is not None:
                                title_skipped += 1
                                continue

                            try:
                                async with session.begin_nested():
                                    await job_repo.create(job_create)
                                title_added += 1
                            except IntegrityError:
                                # A concurrent run inserted the same source_job_id
                                # between our check and insert; the SAVEPOINT rolled
                                # back, so only this row is lost.
                                title_skipped += 1

                        # Commit this title's batch so a later failure in the run
                        # cannot discard postings already gathered.
                        await session.commit()

                        added += title_added
                        skipped += title_skipped
                        logger.info(
                            "sourcing_title_done",
                            extra={
                                "title": title,
                                "location": location,
                                "fetched": len(raw_results),
                                "added": title_added,
                                "skipped": title_skipped,
                            },
                        )

                logger.info(
                    "sourcing_results_persisted",
                    extra={
                        "new_added": added,
                        "duplicates_skipped": skipped,
                        "query_errors": query_errors,
                        "profiles": profiles_processed,
                    },
                )
    except Exception:
        # Never let the scheduler thread die on an unexpected error.
        logger.error("sourcing_job_failed", exc_info=True)
    finally:
        logger.info(
            "sourcing_job_finished",
            extra={
                "new_added": added,
                "duplicates_skipped": skipped,
                "query_errors": query_errors,
                "profiles": profiles_processed,
            },
        )
