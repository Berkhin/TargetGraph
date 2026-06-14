"""Repository layer — the only gateway between business logic and the DB."""

from __future__ import annotations

from app.repositories.job_repository import JobRepository

__all__ = ["JobRepository"]
