"""FastAPI router for master profiles.

Read-only access to the candidate profiles. Follows the same access rule as the
jobs router: endpoints depend on a :class:`ProfileRepository` (which itself
depends on the request-scoped session) and never touch the ``AsyncSession``
directly.

These routes let the frontend discover a real ``profile_id`` for the AI matching
call (``POST /jobs/{id}/match?profile_id=...``) instead of hardcoding one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.models.schemas.profile import ProfileRead
from app.repositories.profile_repository import ProfileRepository

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
