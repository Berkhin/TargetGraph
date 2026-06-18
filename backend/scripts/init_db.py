"""Dev-only helper: create all tables for the configured database.

In production, schema is managed by Alembic migrations. For quick local manual
testing this creates the tables directly from the ORM metadata against whatever
``DATABASE_URL`` (or POSTGRES_* parts) is configured — including a throwaway
SQLite file, e.g.::

    # PowerShell
    $env:DATABASE_URL = "sqlite+aiosqlite:///./dev.db"
    python -m scripts.init_db

Run from the ``backend`` directory.
"""

from __future__ import annotations

import asyncio

import app.models.sql  # noqa: F401 - imports register every table on the metadata
from app.db.base import Base
from app.db.database import engine


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f"Schema created on {engine.url.render_as_string(hide_password=True)}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
