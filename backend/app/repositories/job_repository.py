"""Repository for the ``JobPosting`` entity.

Contract: every public method accepts and returns **Pydantic DTOs only**.
SQLAlchemy entities are an internal implementation detail and never escape this
class. Methods ``flush`` + ``refresh`` so server-generated values (``id``,
``created_at``, ``updated_at``) are populated on the returned DTO before the
surrounding unit of work commits.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.enums import JobStatus
from app.models.schemas.job import JobCreate, JobRead, JobUpdate
from app.models.sql.job_posting import JobPosting
from app.repositories.base import BaseRepository


class JobRepository(BaseRepository):
    """CRUD access for job postings, in terms of DTOs."""

    async def create(self, data: JobCreate) -> JobRead:
        """Persist a new posting and return it as a :class:`JobRead`."""
        entity = JobPosting(**data.model_dump())
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return JobRead.model_validate(entity)

    async def get_by_id(self, job_id: uuid.UUID) -> JobRead | None:
        """Return the posting with ``job_id``, or ``None`` if absent."""
        entity = await self._session.get(JobPosting, job_id)
        return JobRead.model_validate(entity) if entity is not None else None

    async def get_by_status(self, status: JobStatus) -> list[JobRead]:
        """Return postings in ``status``, newest first."""
        stmt = (
            select(JobPosting)
            .where(JobPosting.status == status)
            .order_by(JobPosting.created_at.desc())
        )
        result = await self._session.scalars(stmt)
        return [JobRead.model_validate(entity) for entity in result.all()]

    async def update_status_and_score(
        self, job_id: uuid.UUID, data: JobUpdate
    ) -> JobRead | None:
        """Apply the status/score change to a posting.

        Only fields explicitly set on ``data`` are written, so status and score
        can be updated independently. Returns ``None`` if the posting is absent.
        """
        entity = await self._session.get(JobPosting, job_id)
        if entity is None:
            return None

        changes = data.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(entity, field, value)

        await self._session.flush()
        await self._session.refresh(entity)
        return JobRead.model_validate(entity)
