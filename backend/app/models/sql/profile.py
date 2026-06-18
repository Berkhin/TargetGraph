"""Master Profile tables — SQLAlchemy 2.0 declarative mapping.

A candidate's single source-of-truth profile and its one-to-many children:

* ``master_profiles``    — the profile root (name, target titles, preferences)
* ``profile_experiences`` — work history entries
* ``profile_skills``      — skill groups

JSON-ish columns use ``JSONB`` on PostgreSQL (per the spec) and fall back to the
generic ``JSON`` type elsewhere (e.g. the in-memory SQLite used by the test
suite), so the same mapping is portable across both. Children are loaded
explicitly via ``selectinload`` in the repository, never lazily.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import JSON, Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# JSONB on PostgreSQL, plain JSON elsewhere (keeps SQLite-based tests working).
JSONColumn = JSON().with_variant(JSONB(), "postgresql")


class MasterProfile(Base):
    """The candidate's canonical profile and its related entities."""

    __tablename__ = "master_profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    candidate_name: Mapped[str] = mapped_column(String(255))
    target_titles: Mapped[list[str]] = mapped_column(JSONColumn, default=list)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONColumn, default=dict)

    # lazy="raise": children must be loaded explicitly via selectinload (see
    # ProfileRepository). Any accidental lazy access then fails fast with a clear
    # InvalidRequestError instead of a cryptic MissingGreenlet under asyncio.
    experiences: Mapped[list["ProfileExperience"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    skills: Mapped[list["ProfileSkill"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"MasterProfile(id={self.id!r}, candidate_name={self.candidate_name!r})"
        )


class ProfileExperience(Base):
    """A single work-history entry belonging to a profile."""

    __tablename__ = "profile_experiences"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="CASCADE"), index=True
    )

    company: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(255))
    highlights: Mapped[list[str]] = mapped_column(JSONColumn, default=list)
    start_date: Mapped[datetime.date] = mapped_column(Date)
    end_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)

    profile: Mapped["MasterProfile"] = relationship(back_populates="experiences")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ProfileExperience(id={self.id!r}, company={self.company!r}, "
            f"role={self.role!r})"
        )


class ProfileSkill(Base):
    """A categorised group of skills belonging to a profile."""

    __tablename__ = "profile_skills"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="CASCADE"), index=True
    )

    category: Mapped[str] = mapped_column(String(255))
    skills: Mapped[list[str]] = mapped_column(JSONColumn, default=list)

    profile: Mapped["MasterProfile"] = relationship(back_populates="skills")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ProfileSkill(id={self.id!r}, category={self.category!r})"
