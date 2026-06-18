"""Async engine, session factory, and the FastAPI session dependency.

This module owns the SQLAlchemy 2.0 async machinery:

* ``create_async_engine`` over the ``asyncpg`` driver (lazy — building the engine
  does not open a connection, so importing this module is side-effect free).
* ``async_sessionmaker(..., expire_on_commit=False)`` — the documented setting
  for asyncio, so attributes stay accessible after ``commit()``.
* :func:`get_session` — a request-scoped unit-of-work dependency that commits on
  success and rolls back on error. Endpoints never touch the session directly;
  they depend on a repository which depends on this.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_database_settings

_settings = get_database_settings()

engine: AsyncEngine = create_async_engine(
    _settings.async_url,
    echo=_settings.echo,
    pool_pre_ping=True,  # transparently recycle stale connections
    pool_size=_settings.pool_size,
    max_overflow=_settings.max_overflow,
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session, committing on success.

    Used as a FastAPI dependency. The single commit/rollback here makes the
    whole request one atomic unit of work; repositories only ``flush``.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
