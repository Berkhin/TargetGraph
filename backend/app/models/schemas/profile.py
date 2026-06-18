"""Pydantic DTOs for the Master Profile aggregate.

These are the only types that cross the :class:`ProfileRepository` boundary —
SQLAlchemy entities never leak out. ``from_attributes=True`` lets the ``*Read``
models be built directly from ORM instances (including eagerly-loaded
relationships) via ``model_validate``.

The ``*Create`` models describe one nested write: a profile together with its
experiences and skills, persisted atomically by ``create_full_profile``.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Children                                                                     #
# --------------------------------------------------------------------------- #
class ExperienceCreate(BaseModel):
    """Input DTO for a single work-history entry."""

    model_config = ConfigDict(from_attributes=True)

    company: str = Field(min_length=1, max_length=255)
    role: str = Field(min_length=1, max_length=255)
    highlights: list[str] = Field(default_factory=list)
    start_date: datetime.date
    end_date: datetime.date | None = None


class SkillCreate(BaseModel):
    """Input DTO for a categorised group of skills."""

    model_config = ConfigDict(from_attributes=True)

    category: str = Field(min_length=1, max_length=255)
    skills: list[str] = Field(default_factory=list)


class ExperienceRead(ExperienceCreate):
    """Output DTO — a persisted experience row."""

    id: uuid.UUID


class SkillRead(SkillCreate):
    """Output DTO — a persisted skill row."""

    id: uuid.UUID


# --------------------------------------------------------------------------- #
# Profile root                                                                 #
# --------------------------------------------------------------------------- #
class ProfileCreate(BaseModel):
    """Input DTO for creating a full profile with its nested children."""

    model_config = ConfigDict(from_attributes=True)

    candidate_name: str = Field(min_length=1, max_length=255)
    target_titles: list[str] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)
    experiences: list[ExperienceCreate] = Field(default_factory=list)
    skills: list[SkillCreate] = Field(default_factory=list)


class ProfileUpdate(BaseModel):
    """Input DTO for a full-aggregate replace of an existing profile.

    Mirrors :class:`ProfileCreate`: a PUT replaces the whole profile, including
    its nested experiences and skills (any incoming child has no id — the old
    rows are deleted and these are inserted in their place, see
    ``ProfileRepository.update_full_profile``).
    """

    model_config = ConfigDict(from_attributes=True)

    candidate_name: str = Field(min_length=1, max_length=255)
    target_titles: list[str] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)
    experiences: list[ExperienceCreate] = Field(default_factory=list)
    skills: list[SkillCreate] = Field(default_factory=list)


class ProfileRead(BaseModel):
    """Output DTO — the full persisted profile with children."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_name: str
    target_titles: list[str]
    preferences: dict[str, Any]
    experiences: list[ExperienceRead] = Field(default_factory=list)
    skills: list[SkillRead] = Field(default_factory=list)
