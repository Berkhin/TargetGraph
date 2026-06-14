"""Declarative base for all ORM models (SQLAlchemy 2.0 style).

A shared :class:`MetaData` with an explicit naming convention is attached so
that Alembic autogenerate produces deterministic, named constraints/indexes —
essential for clean, reviewable migrations.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Predictable constraint names (https://alembic.sqlalchemy.org/en/latest/naming.html).
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Common declarative base for every table in the schema."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
