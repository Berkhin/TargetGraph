"""Shared repository base.

Holds the injected :class:`AsyncSession`. Concrete repositories add the
entity-specific queries. Repositories ``flush`` (so generated values are
available) but never ``commit`` — the request-scoped unit of work in
``get_session`` owns the transaction boundary.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """Base class binding a repository to an async session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
