"""Dev-only helper: rebuild the database to a clean, seeded state.

Idempotent one-shot for the common dev loop "I deleted dev.db / changed config
and now nothing works". It:

1. Applies all Alembic migrations up to ``head`` (creates every table on a fresh
   or just-deleted database; a no-op if already current).
2. Seeds the single candidate profile (skipped if one already exists, so it is
   safe to re-run).

Run from the ``backend`` directory::

    python -m scripts.reset_db

This uses migrations (not ``create_all``) so the dev schema matches production.
For a totally fresh DB, delete ``dev.db`` first, then run this.
"""

from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config

from app.db.database import AsyncSessionLocal
from app.repositories.profile_repository import ProfileRepository
from scripts.seed_profile import seed_db


def _upgrade_to_head() -> None:
    """Run ``alembic upgrade head`` via the Python API (no shell needed)."""
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


async def _seed_if_empty() -> None:
    """Seed the candidate profile only when none exists (re-run safe)."""
    async with AsyncSessionLocal() as session:
        repo = ProfileRepository(session)
        existing = await repo.get_first_profile()
    if existing is not None:
        print(f"↺ Profile already present (id={existing.id}); skipping seed.")
        return
    await seed_db()


async def _main() -> None:
    await _seed_if_empty()


if __name__ == "__main__":
    print("→ Applying migrations to head ...")
    _upgrade_to_head()
    print("→ Ensuring candidate profile is seeded ...")
    asyncio.run(_main())
    print("✅ Database ready.")
