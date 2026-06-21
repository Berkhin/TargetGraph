"""The periodic job-sourcing task driven by APScheduler.

This is the seam between the (DB-agnostic) Apify service and persistence. Each
run reads every master profile's target titles + preferred location, runs the
LinkedIn Jobs Apify actor *once per profile*, and persists postings that aren't
already known (deduped by ``source_job_id``). Each new posting is pre-screened by
a cheap LLM relevance check: postings scoring at/above ``_PRESCREEN_THRESHOLD``
land as ``NEW`` for the matching pipeline to pick up; the rest land as
``FILTERED_OUT`` so the board hides them and the pipeline never scores them. The
pre-screen runs only for non-duplicate postings, so known jobs are never
re-scored.

Cost optimisation (the whole point of the Apify migration):

* Every actor run bills an Apify container, so we do **not** loop over each
  target title. Instead all of a profile's titles are OR-joined into a single
  Boolean query and sent in ONE actor run.
* ``runs_made`` is the safety fuse: it counts actor runs this tick and is bounded
  by ``max_runs_per_task`` (default 1), so a single tick can never blow the free
  $5/month tier regardless of how many profiles exist.

Resilience notes (the scheduler must survive everything):

* The whole body is wrapped so an unexpected error is logged, never propagated —
  a thrown task would otherwise be swallowed by APScheduler and leave no trace.
* A failed run (:class:`SourcingError`) is counted and skipped; the task
  continues with the next profile.
* **Transactional radius:** each profile's postings are committed as their own
  batch, and every insert runs inside a SAVEPOINT. So a DB error (or a
  race-condition ``IntegrityError`` from a concurrent run inserting the same
  ``source_job_id``) discards only that one row — never postings already
  committed earlier in the tick.
"""

from __future__ import annotations

from typing import Any

from apify_client import ApifyClientAsync
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.nodes import evaluate_job_relevance
from app.core.config import get_sourcing_settings
from app.core.logging import get_logger
from app.db.database import AsyncSessionLocal
from app.models.enums import JobStatus
from app.repositories.job_repository import JobRepository
from app.repositories.profile_repository import ProfileRepository
from app.services.sourcing import SourcingError, _to_job_create, fetch_jobs_from_apify
from app.utils.formatters import format_profile_to_markdown

logger = get_logger(__name__)

# Minimum pre-screen RELEVANCE score (0-100) for a sourced posting to reach the
# board as ``NEW``. Below this it is stored ``FILTERED_OUT`` so the UI hides it.
# Intentionally LOWER than the match pipeline's MATCHED threshold: the pre-screen
# is a coarse relevance gate (drop only clearly off-target postings), while the
# stricter qualification verdict happens later in the match pipeline, on click.
_PRESCREEN_THRESHOLD = 55


def _resolve_location(
    preferences: dict[str, Any], default: str, *, force_default: bool = False
) -> str:
    """Pick a usable search location from a profile's preferences.

    When ``force_default`` is set the profile's preferred location is ignored and
    ``default`` is always used — LinkedIn returns little for some regions, so
    sourcing from a location with dense coverage beats returning zero results.
    """
    if force_default:
        return default
    location = preferences.get("location") if preferences else None
    if isinstance(location, str) and location.strip():
        return location
    return default


def _build_query(titles: list[str]) -> str:
    """OR-join a profile's target titles into one Boolean query.

    Each title is quoted so multi-word titles match as phrases, e.g.
    ``["AI Engineer", "ML Engineer"]`` -> ``'"AI Engineer" OR "ML Engineer"'``.
    This is what lets a single actor run cover every title (one billed container
    instead of one per title).
    """
    return " OR ".join(f'"{title}"' for title in titles)


async def run_sourcing_job(
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
) -> None:
    """Fetch fresh postings for every profile and persist new ones.

    One Apify actor run per profile (titles OR-joined), bounded by
    ``max_runs_per_task`` so a tick stays inside the free Apify tier.

    Args:
        session_factory: Async session factory (``async_sessionmaker``). Injectable
            so tests can pass a SQLite-backed factory.
    """
    settings = get_sourcing_settings()
    max_runs = settings.max_runs_per_task

    added = 0
    skipped = 0
    filtered_out = 0
    query_errors = 0
    profiles_processed = 0
    # Apify actor runs started this tick (each run == one billed container). The
    # safety fuse: bounded by max_runs_per_task so a single tick can never blow
    # the monthly Apify budget, regardless of how many profiles exist.
    runs_made = 0

    logger.info("sourcing_job_started", extra={"max_runs_per_task": max_runs})
    try:
        client = ApifyClientAsync(token=settings.apify_token)
        async with session_factory() as session:
            profile_repo = ProfileRepository(session)
            job_repo = JobRepository(session)

            profiles = await profile_repo.get_all_profiles()
            if not profiles:
                logger.warning("sourcing_no_profiles")
                return

            for profile in profiles:
                if runs_made >= max_runs:
                    logger.info(
                        "sourcing_run_budget_reached",
                        extra={
                            "max_runs_per_task": max_runs,
                            "runs_made": runs_made,
                        },
                    )
                    break  # tick-level Apify budget exhausted
                titles = profile.target_titles or []
                if not titles:
                    continue
                profiles_processed += 1
                location = _resolve_location(
                    profile.preferences,
                    settings.default_location,
                    force_default=settings.force_default_location,
                )

                # All titles in ONE Boolean query -> one billed actor run.
                query = _build_query(titles)
                try:
                    raw_results = await fetch_jobs_from_apify(
                        query, location, client=client
                    )
                except SourcingError:
                    # Already logged in the service with full context. A failed
                    # run does not count against the budget — it produced no data.
                    query_errors += 1
                    continue

                runs_made += 1

                # Render the candidate's Master Profile once per profile — the
                # pre-screen reuses it for every fetched posting.
                profile_text = format_profile_to_markdown(profile)

                profile_added = 0
                profile_skipped = 0
                profile_filtered = 0
                for raw in raw_results:
                    job_create = _to_job_create(raw)
                    if job_create is None or job_create.source_job_id is None:
                        continue

                    existing = await job_repo.get_by_source_job_id(
                        job_create.source_job_id
                    )
                    if existing is not None:
                        profile_skipped += 1
                        continue

                    # Cheap pre-screen, run ONLY for genuinely new postings (after
                    # the dedup check above) so we never re-score known jobs. A
                    # score below the threshold is persisted FILTERED_OUT — hidden
                    # from the board and never re-scraped — instead of NEW.
                    relevance = await evaluate_job_relevance(
                        job_create.description, profile_text
                    )
                    score = relevance["score"]
                    if score is not None and score < _PRESCREEN_THRESHOLD:
                        status = JobStatus.FILTERED_OUT
                    else:
                        # score >= threshold, or None (pre-screen unavailable):
                        # fail open and let the full pipeline decide later.
                        status = JobStatus.NEW
                    job_create = job_create.model_copy(
                        update={
                            "status": status,
                            "match_score": score,
                            "match_reason": relevance["reason"],
                        }
                    )

                    try:
                        async with session.begin_nested():
                            await job_repo.create(job_create)
                        if status is JobStatus.FILTERED_OUT:
                            profile_filtered += 1
                        else:
                            profile_added += 1
                    except IntegrityError:
                        # A concurrent run inserted the same source_job_id between
                        # our check and insert; the SAVEPOINT rolled back, so only
                        # this row is lost.
                        profile_skipped += 1

                # Commit this profile's batch so a later failure in the tick
                # cannot discard postings already gathered.
                await session.commit()

                added += profile_added
                skipped += profile_skipped
                filtered_out += profile_filtered
                logger.info(
                    "sourcing_profile_done",
                    extra={
                        "query": query,
                        "location": location,
                        "fetched": len(raw_results),
                        "added": profile_added,
                        "skipped": profile_skipped,
                        "filtered_out": profile_filtered,
                    },
                )

            logger.info(
                "sourcing_results_persisted",
                extra={
                    "new_added": added,
                    "duplicates_skipped": skipped,
                    "filtered_out": filtered_out,
                    "query_errors": query_errors,
                    "profiles": profiles_processed,
                    "apify_runs": runs_made,
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
                "filtered_out": filtered_out,
                "query_errors": query_errors,
                "profiles": profiles_processed,
                "apify_runs": runs_made,
            },
        )
