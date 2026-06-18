"""Tests for the periodic sourcing task (run_sourcing_job).

Unlike the repository tests (which use a single session), the task opens its own
session, so these tests need a *factory* whose sessions all share one in-memory
SQLite database — hence ``StaticPool``. ``fetch_jobs_from_google`` is monkeypatched
so no HTTP happens; we assert persistence, dedup, and resilience behaviour.
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
    # SERPAPI_KEY comes via its env alias (default_location defaults to
    # "United States", which test_falls_back_to_default_location relies on).
    monkeypatch.setenv("SERPAPI_KEY", "test-key")
    settings = SourcingSettings()
    monkeypatch.setattr(sourcing_task, "get_sourcing_settings", lambda: settings)


async def _seed_profile(
    factory: async_sessionmaker[AsyncSession],
    *,
    target_titles: list[str],
    location: str | None = "Berlin",
) -> None:
    async with factory() as session:
        prefs = {"location": location} if location is not None else {}
        await ProfileRepository(session).create_full_profile(
            ProfileCreate(
                candidate_name="Tester",
                target_titles=target_titles,
                preferences=prefs,
            )
        )
        await session.commit()


def _raw(job_id: str, title: str = "AI Engineer") -> dict:
    return {
        "job_id": job_id,
        "title": title,
        "company_name": "Acme",
        "description": "Build things.",
        "share_link": f"https://g.co/{job_id}",
    }


async def _statuses(factory: async_sessionmaker[AsyncSession]) -> list:
    async with factory() as session:
        return await JobRepository(session).get_by_status(JobStatus.NEW)


async def test_persists_new_jobs_and_dedups_on_second_run(factory, monkeypatch) -> None:
    await _seed_profile(factory, target_titles=["AI Engineer"])

    async def fake_fetch(query, location, *, client=None, max_pages=None):
        assert query == "AI Engineer"
        assert location == "Berlin"  # from profile preferences
        return [_raw("a"), _raw("b")]

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_google", fake_fetch)

    await run_sourcing_job(session_factory=factory)
    first = await _statuses(factory)
    assert {j.source_job_id for j in first} == {"a", "b"}
    assert all(j.status is JobStatus.NEW for j in first)

    # Second run: same results → all skipped as duplicates, no new rows.
    await run_sourcing_job(session_factory=factory)
    second = await _statuses(factory)
    assert {j.source_job_id for j in second} == {"a", "b"}
    assert len(second) == 2


async def test_query_error_does_not_abort_run(factory, monkeypatch) -> None:
    await _seed_profile(factory, target_titles=["good", "bad", "good2"])

    async def fake_fetch(query, location, *, client=None, max_pages=None):
        if query == "bad":
            raise SourcingError("upstream 503")
        if query == "good":
            return [_raw("A", title="good")]
        return [_raw("B", title="good2")]

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_google", fake_fetch)

    await run_sourcing_job(session_factory=factory)

    jobs = await _statuses(factory)
    # The failing middle query is skipped; postings from the other titles persist.
    assert {j.source_job_id for j in jobs} == {"A", "B"}


async def test_falls_back_to_default_location(factory, monkeypatch) -> None:
    await _seed_profile(factory, target_titles=["AI Engineer"], location=None)

    seen_locations: list[str] = []

    async def fake_fetch(query, location, *, client=None, max_pages=None):
        seen_locations.append(location)
        return []

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_google", fake_fetch)

    await run_sourcing_job(session_factory=factory)
    assert seen_locations == ["United States"]  # config default


async def test_no_profiles_is_a_noop(factory, monkeypatch) -> None:
    async def fake_fetch(query, location, *, client=None, max_pages=None):
        raise AssertionError("should not be called when there are no profiles")

    monkeypatch.setattr(sourcing_task, "fetch_jobs_from_google", fake_fetch)

    await run_sourcing_job(session_factory=factory)  # must not raise
    assert await _statuses(factory) == []
