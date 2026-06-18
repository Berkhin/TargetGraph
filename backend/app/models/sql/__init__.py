"""SQLAlchemy ORM tables.

Importing this package registers every model on ``Base.metadata`` so that
Alembic autogenerate and ``create_all`` see the full schema.
"""

from __future__ import annotations

from app.models.sql.job_posting import JobPosting

__all__ = ["JobPosting"]
