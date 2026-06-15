"""Repository layer — the only gateway between business logic and the DB."""

from __future__ import annotations

from app.repositories.job_repository import JobRepository
from app.repositories.profile_repository import ProfileRepository

__all__ = ["JobRepository", "ProfileRepository"]
