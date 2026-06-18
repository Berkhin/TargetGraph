"""Endpoint tests for the job CRUD routes — focused on soft-delete.

Exercises ``DELETE /api/v1/jobs/{job_id}`` via httpx's in-process transport,
with the DB ``get_session`` dependency overridden by the in-memory SQLite
session (same pattern as ``test_outreach_api``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.main import app
from app.models.enums import JobStatus
from app.models.schemas.job import JobCreate
from app.repositories.job_repository import JobRepository


def _wire(session: AsyncSession) -> AsyncClient:
    """Build an httpx client with the session dependency overridden."""

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def _make_job(session: AsyncSession) -> uuid.UUID:
    job = await JobRepository(session).create(
        JobCreate(
            company_name="Acme",
            job_title="Engineer",
            description="Build things",
            source_url="https://example.com/jobs/1",
            status=JobStatus.MATCHED,
        )
    )
    return job.id


@pytest.mark.asyncio
async def test_delete_job_soft_deletes(session: AsyncSession) -> None:
    """DELETE marks the posting DISCARDED and drops it off the MATCHED board."""
    job_id = await _make_job(session)
    client = _wire(session)
    try:
        async with client:
            resp = await client.delete(f"/api/v1/jobs/{job_id}")
            listed = await client.get("/api/v1/jobs", params={"job_status": "MATCHED"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 204
    # Soft delete: the row still exists but is now DISCARDED (kept for dedup).
    job = await JobRepository(session).get_by_id(job_id)
    assert job is not None
    assert job.status == JobStatus.DISCARDED
    # ...and it no longer appears on the MATCHED board.
    assert all(item["id"] != str(job_id) for item in listed.json())


@pytest.mark.asyncio
async def test_delete_job_404_for_unknown(session: AsyncSession) -> None:
    client = _wire(session)
    try:
        async with client:
            resp = await client.delete(f"/api/v1/jobs/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404
