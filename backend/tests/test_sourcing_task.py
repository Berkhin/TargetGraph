"""Tests for the periodic sourcing task (run_sourcing_job).

Unlike the repository tests (which use a single session), the task opens its own
session, so these tests need a *factory* whose sessions all share one in-memory
SQLite database — hence ``StaticPool``. ``fetch_jobs_from_apify`` is monkeypatched
so no Apify run happens; we assert persistence, dedup, the one-run-per-profile
Boolean query, the runs budget, and resilience behaviour.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

import app.models.sql  # noqa: F401 - registers tables on Base.metadata
from app.core.config import SourcingSettings
from app.db.base import Base
from app.models.enums import JobStatus
from app.models.schemas.profile import ProfileCreate
from app.repositories.job_repository import JobRepository
from app.repositories.profile_repository import ProfileRepository
from app.services.sourcing import SourcingError
from app.tasks import sourcing_task
from app.tasks.sourcing_task import run_sourcing_job


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory over one shared in-memory SQLite DB (StaticPool)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    await engine.dispose()


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch) -> None:
    # APIFY_TOKEN comes via its env alias; default_location defaults to
    # "Israel", which test_falls_back_to_default_location relies on.
    # ApifyClientAsync is stubbed so constructing the client touches no network.
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    settings = SourcingSettings()
    monkeypatch.setattr(sourcing_task, "get_sourcing_settings", lambda: settings)
    monkeypatch.setattr(sourcing_task, "ApifyClientAsync", lambda token: object())


@pytest.fixture(autouse=True)
def _patch_prescreen(monkeypatch) -> None:
    """Stub the LLM pre-screen so no Gemini call happens.

    Default verdict is a high score, so postings land as NEW — the assumption the
    pre-existing persistence/dedup/budget tests are written against. Tests that
    care about the filter override this with their own monkeypatch.
    """

    async def fake_relevance(job_description, profile_data):
        return {"score": 95, "reason": "strong fit"}

    monkeypatch.setattr(sourcing_task, "evaluate_job_relevance", fake_relevance)


async def _seed_profile(
    factory: async_sessionmaker[AsyncSession],
    *,
    target_titles: list[str],
    location: str | None = "Berlin",
    candidate_name: str = "Tester",
) -> None:
    async with factory() as session:
        prefs = {"location": location} if location is not None else {}
        await ProfileRepository(session).create_full_profile(
            ProfileCreate(
                candidate_name=candidate_name,
                target_titles=target_titles,
                preferences=prefs,
            )
        )
        await session.commit()


def _raw(job_id: str, title: str = "AI Engineer") -> dict:
    return {
        "job_id": job_id,
        "job_title": title,
        "company": "Acme",
        "description": "Build things.",
        "job_url": f"https://www.linkedin.com/jobs/view/{job_id}",
    }


async def _statuses(factory: async_sessionmaker[AsyncSession]) -> list:
    async with factory() as session:
        return await JobRepository(session).get_by_status(JobStatus.NEW)


async def _filtered(factory: async_sessionmaker[AsyncSession]) -> list:
    async with factory() as session:
        return await JobRepository(session).get_by_status(JobStatus.FILTERED_OUT)


async def test_persists_new_jobs_and_dedups_on_second_run(factory, monkeypatch) -> None:
    await _seed_profile(factory, target_titles=["AI Engineer"])

    async def fake_fetch(query, location, *, client=None):
        # A single-title profile still becomes a quoted Boolean query.
        assert query == '"AI Engineer"'
        # force_default_location defaults True, so the profile's "Berlin" is
        # ignored in favour of the configured default with dense coverage.
        assert location == "Israel"
        return [_raw("a"), _raw("b")]

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_apify", fake_fetch)

    await run_sourcing_job(session_factory=factory)
    first = await _statuses(factory)
    assert {j.source_job_id for j in first} == {"a", "b"}
    assert all(j.status is JobStatus.NEW for j in first)

    # Second run: same results → all skipped as duplicates, no new rows.
    await run_sourcing_job(session_factory=factory)
    second = await _statuses(factory)
    assert {j.source_job_id for j in second} == {"a", "b"}
    assert len(second) == 2


async def test_joins_titles_into_one_boolean_query(factory, monkeypatch) -> None:
    # Cost optimisation: many titles, ONE actor run with an OR-joined query.
    await _seed_profile(factory, target_titles=["AI Engineer", "ML Engineer", "MLOps"])

    queries: list[str] = []

    async def fake_fetch(query, location, *, client=None):
        queries.append(query)
        return [_raw("a")]

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_apify", fake_fetch)

    await run_sourcing_job(session_factory=factory)

    assert queries == ['"AI Engineer" OR "ML Engineer" OR "MLOps"']  # one run, joined


async def test_query_error_does_not_abort_run(factory, monkeypatch) -> None:
    # Three profiles; the middle one's run fails. Need a budget that allows all.
    await _seed_profile(factory, target_titles=["good"], candidate_name="A")
    await _seed_profile(factory, target_titles=["bad"], candidate_name="B")
    await _seed_profile(factory, target_titles=["good2"], candidate_name="C")

    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    monkeypatch.setenv("SOURCING_MAX_RUNS_PER_TASK", "3")
    settings = SourcingSettings()
    monkeypatch.setattr(sourcing_task, "get_sourcing_settings", lambda: settings)

    async def fake_fetch(query, location, *, client=None):
        if query == '"bad"':
            raise SourcingError("upstream actor error")
        if query == '"good"':
            return [_raw("A", title="good")]
        return [_raw("B", title="good2")]

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_apify", fake_fetch)

    await run_sourcing_job(session_factory=factory)

    jobs = await _statuses(factory)
    # The failing profile is skipped; postings from the other profiles persist.
    assert {j.source_job_id for j in jobs} == {"A", "B"}


async def test_falls_back_to_default_location(factory, monkeypatch) -> None:
    await _seed_profile(factory, target_titles=["AI Engineer"], location=None)

    seen_locations: list[str] = []

    async def fake_fetch(query, location, *, client=None):
        seen_locations.append(location)
        return []

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_apify", fake_fetch)

    await run_sourcing_job(session_factory=factory)
    assert seen_locations == ["Israel"]  # config default


async def test_force_default_location_overrides_profile(factory, monkeypatch) -> None:
    # With the default flag on, a profile's own location is ignored (some regions
    # return little on LinkedIn, e.g. "Tel Aviv").
    await _seed_profile(factory, target_titles=["AI Engineer"], location="Tel Aviv")

    seen_locations: list[str] = []

    async def fake_fetch(query, location, *, client=None):
        seen_locations.append(location)
        return []

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_apify", fake_fetch)

    await run_sourcing_job(session_factory=factory)
    assert seen_locations == ["Israel"]  # forced default, not "Tel Aviv"


async def test_honours_profile_location_when_force_disabled(factory, monkeypatch) -> None:
    await _seed_profile(factory, target_titles=["AI Engineer"], location="Tel Aviv")

    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    monkeypatch.setenv("SOURCING_FORCE_DEFAULT_LOCATION", "false")
    settings = SourcingSettings()
    monkeypatch.setattr(sourcing_task, "get_sourcing_settings", lambda: settings)

    seen_locations: list[str] = []

    async def fake_fetch(query, location, *, client=None):
        seen_locations.append(location)
        return []

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_apify", fake_fetch)

    await run_sourcing_job(session_factory=factory)
    assert seen_locations == ["Tel Aviv"]  # profile preference honoured


async def test_respects_max_runs_per_task(factory, monkeypatch) -> None:
    # 3 profiles but a budget of 1 → only ONE actor run is started.
    await _seed_profile(factory, target_titles=["t1"], candidate_name="A")
    await _seed_profile(factory, target_titles=["t2"], candidate_name="B")
    await _seed_profile(factory, target_titles=["t3"], candidate_name="C")

    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    monkeypatch.setenv("SOURCING_MAX_RUNS_PER_TASK", "1")
    settings = SourcingSettings()
    monkeypatch.setattr(sourcing_task, "get_sourcing_settings", lambda: settings)

    calls: list[str] = []

    async def fake_fetch(query, location, *, client=None):
        calls.append(query)
        return [_raw(query, title=query)]

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_apify", fake_fetch)

    await run_sourcing_job(session_factory=factory)

    assert len(calls) == 1  # stopped at the runs budget, not all 3 profiles
    assert len(await _statuses(factory)) == 1


async def test_no_profiles_is_a_noop(factory, monkeypatch) -> None:
    async def fake_fetch(query, location, *, client=None):
        raise AssertionError("should not be called when there are no profiles")

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_apify", fake_fetch)

    await run_sourcing_job(session_factory=factory)  # must not raise
    assert await _statuses(factory) == []


async def test_low_score_is_filtered_out(factory, monkeypatch) -> None:
    # Pre-screen returns below the threshold → the posting is persisted
    # FILTERED_OUT (off the board) with its score and reason, not NEW.
    await _seed_profile(factory, target_titles=["AI Engineer"])

    async def fake_fetch(query, location, *, client=None):
        return [_raw("low")]

    async def fake_relevance(job_description, profile_data):
        return {"score": 50, "reason": "missing core hard skills"}

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_apify", fake_fetch)
    monkeypatch.setattr(sourcing_task, "evaluate_job_relevance", fake_relevance)

    await run_sourcing_job(session_factory=factory)

    assert await _statuses(factory) == []  # nothing reached the board
    filtered = await _filtered(factory)
    assert len(filtered) == 1
    assert filtered[0].source_job_id == "low"
    assert filtered[0].match_score == 50
    assert filtered[0].match_reason == "missing core hard skills"


async def test_high_score_lands_new_with_score_and_reason(factory, monkeypatch) -> None:
    await _seed_profile(factory, target_titles=["AI Engineer"])

    async def fake_fetch(query, location, *, client=None):
        return [_raw("hi")]

    async def fake_relevance(job_description, profile_data):
        return {"score": 88, "reason": "strong overlap"}

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_apify", fake_fetch)
    monkeypatch.setattr(sourcing_task, "evaluate_job_relevance", fake_relevance)

    await run_sourcing_job(session_factory=factory)

    new = await _statuses(factory)
    assert len(new) == 1
    assert new[0].status is JobStatus.NEW
    assert new[0].match_score == 88
    assert new[0].match_reason == "strong overlap"


async def test_prescreen_unavailable_keeps_new(factory, monkeypatch) -> None:
    # Fail-open: a None score (Gemini outage) must not drop the job — keep it NEW
    # so the full pipeline can decide later.
    await _seed_profile(factory, target_titles=["AI Engineer"])

    async def fake_fetch(query, location, *, client=None):
        return [_raw("unk")]

    async def fake_relevance(job_description, profile_data):
        return {"score": None, "reason": "Pre-screen unavailable."}

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_apify", fake_fetch)
    monkeypatch.setattr(sourcing_task, "evaluate_job_relevance", fake_relevance)

    await run_sourcing_job(session_factory=factory)

    new = await _statuses(factory)
    assert len(new) == 1
    assert new[0].status is JobStatus.NEW
    assert new[0].match_score is None
    assert await _filtered(factory) == []


async def test_prescreen_skipped_for_duplicates(factory, monkeypatch) -> None:
    # The pre-screen runs only for genuinely new postings: on a second run the
    # known job is deduped before the (costly) LLM call.
    await _seed_profile(factory, target_titles=["AI Engineer"])

    async def fake_fetch(query, location, *, client=None):
        return [_raw("dup")]

    calls: list[str] = []

    async def fake_relevance(job_description, profile_data):
        calls.append(job_description)
        return {"score": 95, "reason": "ok"}

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_apify", fake_fetch)
    monkeypatch.setattr(sourcing_task, "evaluate_job_relevance", fake_relevance)

    await run_sourcing_job(session_factory=factory)
    await run_sourcing_job(session_factory=factory)

    assert len(calls) == 1  # second run deduped before the pre-screen
