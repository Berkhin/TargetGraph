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

    async def get_by_source_job_id(self, source_job_id: str) -> JobRead | None:
        """Return the posting with ``source_job_id``, or ``None`` if absent.

        Used by the sourcing task to deduplicate against postings already
        ingested in a previous run (the column carries a unique index).
        """
        stmt = select(JobPosting).where(JobPosting.source_job_id == source_job_id)
        entity = (await self._session.scalars(stmt)).first()
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

    async def save_match_results(
        self,
        job_id: uuid.UUID,
        match_score: int,
        cover_letter_draft: str,
        status: JobStatus,
        tailored_cv_draft: str | None = None,
    ) -> JobRead | None:
        """Save match results from the AI pipeline.

        Updates the posting with the match score, cover letter draft, tailored CV
        draft, and status. ``tailored_cv_draft`` is optional so callers that do
        not produce a CV (or where the CV node degraded to ``None``) leave the
        column untouched-by-intent at ``None``. Returns ``None`` if the posting
        is absent.
        """
        entity = await self._session.get(JobPosting, job_id)
        if entity is None:
            return None

        entity.match_score = match_score
        entity.cover_letter_draft = cover_letter_draft
        entity.tailored_cv_draft = tailored_cv_draft
        entity.status = status

        await self._session.flush()
        await self._session.refresh(entity)
        return JobRead.model_validate(entity)
