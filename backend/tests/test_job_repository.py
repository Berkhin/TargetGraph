"""Contract tests for JobRepository (in-memory async SQLite)."""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobStatus
from app.models.schemas.job import JobCreate, JobRead, JobUpdate
from app.models.sql.job_posting import JobPosting
from app.repositories.job_repository import JobRepository


def _new_job(company: str = "Acme", title: str = "Backend Engineer") -> JobCreate:
    return JobCreate(
        company_name=company,
        job_title=title,
        description="Build things.",
        source_url="https://jobs.example.com/1",
    )


async def test_create_returns_dto_with_server_values(session: AsyncSession) -> None:
    repo = JobRepository(session)
    created = await repo.create(_new_job())

    # Repository returns a DTO, never an ORM object.
    assert isinstance(created, JobRead)
    assert isinstance(created.id, uuid.UUID)
    assert created.status is JobStatus.NEW  # default applied
    assert created.match_score is None
    assert created.created_at is not None
    assert created.updated_at is not None


async def test_get_by_id_found_and_missing(session: AsyncSession) -> None:
    repo = JobRepository(session)
    created = await repo.create(_new_job())

    found = await repo.get_by_id(created.id)
    assert found is not None
    assert found.id == created.id

    assert await repo.get_by_id(uuid.uuid4()) is None


async def test_get_by_status_filters(session: AsyncSession) -> None:
    repo = JobRepository(session)
    a = await repo.create(_new_job(company="A"))
    b = await repo.create(_new_job(company="B"))
    await repo.update_status_and_score(b.id, JobUpdate(status=JobStatus.MATCHED))

    new_jobs = await repo.get_by_status(JobStatus.NEW)
    assert [j.id for j in new_jobs] == [a.id]

    matched = await repo.get_by_status(JobStatus.MATCHED)
    assert [j.id for j in matched] == [b.id]


async def test_get_by_status_orders_newest_first(session: AsyncSession) -> None:
    # Insert ORM rows with explicit, distinct created_at so ordering is
    # deterministic (func.now() has second-resolution on SQLite, which would
    # otherwise make rows created in the same test tie).
    base = datetime.datetime(2026, 1, 1, 12, 0, 0)
    rows = [
        JobPosting(
            company_name=name,
            job_title="Engineer",
            description="d",
            source_url="https://jobs.example.com/x",
            status=JobStatus.NEW,
            created_at=created,
            updated_at=created,
        )
        for name, created in (
            ("oldest", base),
            ("newest", base + datetime.timedelta(hours=2)),
            ("middle", base + datetime.timedelta(hours=1)),
        )
    ]
    session.add_all(rows)
    await session.flush()

    repo = JobRepository(session)
    ordered = await repo.get_by_status(JobStatus.NEW)
    assert [j.company_name for j in ordered] == ["newest", "middle", "oldest"]


async def test_update_status_and_score(session: AsyncSession) -> None:
    repo = JobRepository(session)
    created = await repo.create(_new_job())

    updated = await repo.update_status_and_score(
        created.id, JobUpdate(status=JobStatus.MATCHED, match_score=87)
    )
    assert updated is not None
    assert updated.status is JobStatus.MATCHED
    assert updated.match_score == 87


async def test_partial_update_only_touches_set_fields(session: AsyncSession) -> None:
    repo = JobRepository(session)
    created = await repo.create(_new_job())
    await repo.update_status_and_score(created.id, JobUpdate(match_score=50))

    # status untouched (still NEW), only score changed
    refreshed = await repo.get_by_id(created.id)
    assert refreshed is not None
    assert refreshed.status is JobStatus.NEW
    assert refreshed.match_score == 50


async def test_update_missing_returns_none(session: AsyncSession) -> None:
    repo = JobRepository(session)
    result = await repo.update_status_and_score(
        uuid.uuid4(), JobUpdate(status=JobStatus.REJECTED_BY_AI)
    )
    assert result is None


async def test_score_validation_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        JobUpdate(match_score=150)


async def test_get_by_source_job_id_found_and_missing(session: AsyncSession) -> None:
    repo = JobRepository(session)
    job = _new_job()
    job.source_job_id = "serpapi-abc123"
    created = await repo.create(job)

    found = await repo.get_by_source_job_id("serpapi-abc123")
    assert found is not None
    assert found.id == created.id
    assert found.source_job_id == "serpapi-abc123"

    assert await repo.get_by_source_job_id("does-not-exist") is None
