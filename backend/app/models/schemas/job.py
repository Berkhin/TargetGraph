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

    # Rich metadata from the LinkedIn jobs scraper. All optional — older rows and
    # sparse scraper results may omit any of them.
    location: str | None = Field(default=None, max_length=255)
    employment_type: str | None = Field(default=None, max_length=100)
    seniority_level: str | None = Field(default=None, max_length=100)
    salary: str | None = Field(default=None, max_length=255)
    # The employer's own website (Apify ``companyWebsite``); carries the real
    # company domain used for the Hunter.io recruiter lookup. Inherited by
    # JobCreate and JobRead.
    company_website: str | None = Field(default=None, max_length=255)
    # Cold-outreach contact resolved during matching (Hunter.io). Both inherited
    # by JobCreate and JobRead; null until find_recruiter_contact resolves one.
    recruiter_name: str | None = Field(default=None, max_length=255)
    recruiter_email: str | None = Field(default=None, max_length=255)


class JobCreate(JobBase):
    """Input DTO for creating a posting (status defaults to NEW)."""

    status: JobStatus = JobStatus.NEW
    match_score: int | None = Field(default=None, ge=0, le=100)
    match_reason: str | None = None
    cover_letter_draft: str | None = None
    tailored_cv_draft: str | None = None
    # Stable provider id for dedup (e.g. SerpAPI google_jobs job_id); None for
    # manually-created postings.
    source_job_id: str | None = Field(default=None, max_length=512)


class JobUpdate(BaseModel):
    """Partial-update DTO for the matching pipeline.

    Only fields that are *explicitly set* are applied, so ``status``,
    ``match_score``, and ``cover_letter_draft`` can be updated independently.
    """

    model_config = ConfigDict(from_attributes=True)

    status: JobStatus | None = None
    match_score: int | None = Field(default=None, ge=0, le=100)
    match_reason: str | None = None
    cover_letter_draft: str | None = None
    tailored_cv_draft: str | None = None
    location: str | None = Field(default=None, max_length=255)
    employment_type: str | None = Field(default=None, max_length=100)
    seniority_level: str | None = Field(default=None, max_length=100)
    salary: str | None = Field(default=None, max_length=255)
    company_website: str | None = Field(default=None, max_length=255)
    recruiter_name: str | None = Field(default=None, max_length=255)
    recruiter_email: str | None = Field(default=None, max_length=255)


class JobRead(JobBase):
    """Output DTO — the full persisted row."""

    id: uuid.UUID
    status: JobStatus
    match_score: int | None
    match_reason: str | None
    cover_letter_draft: str | None
    tailored_cv_draft: str | None
    source_job_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class JobMatchResponse(JobRead):
    """Response DTO for the AI matching pipeline.

    Extends JobRead with the full matched job state after running the pipeline.
    """

    pass
