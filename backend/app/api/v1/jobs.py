"""FastAPI router for job postings.

Demonstrates the access rule: endpoints depend on a :class:`JobRepository`
(which itself depends on the request-scoped session) and never touch the
``AsyncSession`` directly. Maps the contract from API_Contracts.md.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.models.enums import JobStatus
from app.models.schemas.job import JobCreate, JobRead, JobUpdate
from app.repositories.job_repository import JobRepository

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def get_job_repository(
    session: AsyncSession = Depends(get_session),
) -> JobRepository:
    """Provide a repository bound to the request-scoped session."""
    return JobRepository(session)


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreate,
    repo: JobRepository = Depends(get_job_repository),
) -> JobRead:
    """Add a new job posting."""
    return await repo.create(payload)


@router.get("", response_model=list[JobRead])
async def list_jobs(
    job_status: JobStatus,
    repo: JobRepository = Depends(get_job_repository),
) -> list[JobRead]:
    """List job postings filtered by status (``?job_status=NEW``)."""
    return await repo.get_by_status(job_status)


@router.get("/{job_id}", response_model=JobRead)
async def get_job(
    job_id: uuid.UUID,
    repo: JobRepository = Depends(get_job_repository),
) -> JobRead:
    """Fetch a single posting by id."""
    job = await repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job posting not found")
    return job


@router.patch("/{job_id}", response_model=JobRead)
async def update_job_status_and_score(
    job_id: uuid.UUID,
    payload: JobUpdate,
    repo: JobRepository = Depends(get_job_repository),
) -> JobRead:
    """Update a posting's status and/or match score."""
    job = await repo.update_status_and_score(job_id, payload)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job posting not found")
    return job
