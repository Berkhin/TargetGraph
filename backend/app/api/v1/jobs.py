"""FastAPI router for job postings.

Demonstrates the access rule: endpoints depend on a :class:`JobRepository`
(which itself depends on the request-scoped session) and never touch the
``AsyncSession`` directly. Maps the contract from API_Contracts.md.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.models.enums import JobStatus
from app.models.schemas.job import JobCreate, JobMatchResponse, JobRead, JobUpdate
from app.repositories.job_repository import JobRepository
from app.services.orchestrator import (
    JobNotFoundError,
    ProfileNotFoundError,
    PipelineExecutionError,
    run_pipeline,
)

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


@router.post("/{job_id}/match", response_model=JobMatchResponse)
async def match_job(
    job_id: uuid.UUID,
    profile_id: uuid.UUID = Query(...),
    session: AsyncSession = Depends(get_session),
) -> JobMatchResponse:
    """Run the AI matching pipeline for a job and profile, save results to DB.

    Query parameters:
        profile_id: UUID of the candidate profile to match against the job.

    Returns:
        The updated job posting with match score, cover letter draft, and status.

    Raises:
        404: If job_id or profile_id does not exist in the database.
        422: If AI pipeline execution fails.
    """
    try:
        pipeline_result = await run_pipeline(
            job_id, profile_id, session, save_results=False
        )
    except JobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"job posting {job_id} not found",
        )
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"profile {profile_id} not found",
        )
    except PipelineExecutionError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AI pipeline execution failed. Please try again later.",
        )

    # Save results at the end, after all checks pass
    match_score = pipeline_result.get("match_score", 0)
    cover_letter = pipeline_result.get("cover_letter_draft", "")
    result_status = (
        JobStatus.MATCHED if match_score >= 70 else JobStatus.REJECTED_BY_AI
    )

    repo = JobRepository(session)
    await repo.save_match_results(job_id, match_score, cover_letter, result_status)

    # Fetch the updated job and return it
    job = await repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="job posting disappeared after pipeline execution",
        )

    return JobMatchResponse.model_validate(job)
