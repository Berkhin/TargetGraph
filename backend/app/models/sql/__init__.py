"""SQLAlchemy ORM tables.

Importing this package registers every model on ``Base.metadata`` so that
Alembic autogenerate and ``create_all`` see the full schema.
"""

from __future__ import annotations

from app.models.sql.job_posting import JobPosting
from app.models.sql.profile import (
    MasterProfile,
    ProfileExperience,
    ProfileSkill,
)

__all__ = [
    "JobPosting",
    "MasterProfile",
    "ProfileExperience",
    "ProfileSkill",
]
