"""FastAPI router for master profiles.

Read-only access to the candidate profiles. Follows the same access rule as the
jobs router: endpoints depend on a :class:`ProfileRepository` (which itself
depends on the request-scoped session) and never touch the ``AsyncSession``
directly.

These routes let the frontend discover a real ``profile_id`` for the AI matching
call (``POST /jobs/{id}/match?profile_id=...``) instead of hardcoding one.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.models.schemas.profile import ProfileCreate, ProfileRead, ProfileUpdate
from app.repositories.profile_repository import ProfileRepository
from app.services.resume_parser import create_profile_from_resume

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])


def get_profile_repository(
    session: AsyncSession = Depends(get_session),
) -> ProfileRepository:
    """Provide a repository bound to the request-scoped session."""
    return ProfileRepository(session)


@router.get("", response_model=list[ProfileRead])
async def list_profiles(
    repo: ProfileRepository = Depends(get_profile_repository),
) -> list[ProfileRead]:
    """List all candidate profiles (with experiences and skills)."""
    return await repo.get_all_profiles()


@router.post("", response_model=ProfileRead)
async def create_profile(
    payload: ProfileCreate,
    repo: ProfileRepository = Depends(get_profile_repository),
) -> ProfileRead:
    """Create a new candidate profile with experiences and skills."""
    profile = await repo.create_full_profile(payload)
    logger.info(
        "profile_created",
        extra={"candidate_name": profile.candidate_name},
    )
    return profile


@router.get("/active", response_model=ProfileRead)
async def get_active_profile(
    repo: ProfileRepository = Depends(get_profile_repository),
) -> ProfileRead:
    """Return the active candidate profile.

    Convenience for the single-candidate use case: there is no explicit
    "active" flag yet, so a single profile is selected deterministically (see
    ``get_first_profile``). Returns 404 when no profile exists.
    """
    profile = await repo.get_first_profile()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no candidate profile exists",
        )
    return profile


@router.post("/upload-resume", response_model=ProfileRead)
async def upload_resume(
    file: UploadFile = File(...),
    repo: ProfileRepository = Depends(get_profile_repository),
) -> ProfileRead:
    """Parse a PDF resume and create a profile.

    Accepts a PDF file, extracts text, uses LLM to parse structured data
    (name, experiences, skills, target titles), and creates a profile.
    Returns 400 if the file is not a PDF or cannot be parsed.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a PDF",
        )

    try:
        pdf_bytes = await file.read()
        if not pdf_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF file is empty",
            )

        profile_create = await create_profile_from_resume(pdf_bytes)

        if profile_create is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not parse resume. Please ensure it is a valid resume PDF.",
            )

        profile = await repo.create_full_profile(profile_create)
        logger.info(
            "profile_created_from_resume",
            extra={"candidate_name": profile.candidate_name},
        )
        return profile

    except HTTPException:
        raise
    except Exception as e:
        logger.error("upload_resume failed", extra={"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process resume",
        )


@router.put("/{profile_id}", response_model=ProfileRead)
async def update_profile(
    profile_id: uuid.UUID,
    payload: ProfileUpdate,
    repo: ProfileRepository = Depends(get_profile_repository),
) -> ProfileRead:
    """Replace a candidate profile (and its experiences/skills) wholesale.

    Returns 404 when no profile exists for ``profile_id``.
    """
    profile = await repo.update_full_profile(profile_id, payload)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"profile {profile_id} not found",
        )
    return profile
