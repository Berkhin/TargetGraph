"""Pydantic DTOs for the ``JobPosting`` entity.

These are the *only* types that cross the repository boundary — SQLAlchemy
objects never leak out. ``from_attributes=True`` lets ``JobRead`` be built
directly from an ORM instance via ``model_validate``.
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import JobStatus


class JobBase(BaseModel):
    """Fields common to creation and reading."""

    model_config = ConfigDict(from_attributes=True)

    company_name: str = Field(min_length=1, max_length=255)
    job_title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    source_url: str = Field(min_length=1, max_length=2048)


class JobCreate(JobBase):
    """Input DTO for creating a posting (status defaults to NEW)."""

    status: JobStatus = JobStatus.NEW
    match_score: int | None = Field(default=None, ge=0, le=100)


class JobUpdate(BaseModel):
    """Partial-update DTO for the matching pipeline.

    Only fields that are *explicitly set* are applied, so ``status`` and
    ``match_score`` can be updated independently.
    """

    model_config = ConfigDict(from_attributes=True)

    status: JobStatus | None = None
    match_score: int | None = Field(default=None, ge=0, le=100)


class JobRead(JobBase):
    """Output DTO — the full persisted row."""

    id: uuid.UUID
    status: JobStatus
    match_score: int | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
