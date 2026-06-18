"""Shared fixtures for data-layer tests.

Repository tests run against an in-memory async SQLite database (``aiosqlite``)
so they exercise the real SQLAlchemy mapping and queries without needing a live
PostgreSQL instance. The mapping is portable: ``Uuid`` falls back to CHAR,
``Enum`` to VARCHAR+CHECK, and ``func.now()`` to ``CURRENT_TIMESTAMP``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base
from app.models.sql import JobPosting  # noqa: F401 - registers the table on metadata


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Yield a session against a fresh in-memory SQLite schema per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session

    await engine.dispose()
