"""Repository for the Master Profile aggregate.

Contract: every public method accepts and returns **Pydantic DTOs only**.
SQLAlchemy entities are an internal implementation detail and never escape this
class. Like the other repositories, methods ``flush`` (so server-generated
values are available) but never ``commit`` — the surrounding unit of work owns
the transaction boundary.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.schemas.profile import ProfileCreate, ProfileRead
from app.models.sql.profile import MasterProfile, ProfileExperience, ProfileSkill
from app.repositories.base import BaseRepository


class ProfileRepository(BaseRepository):
    """Nested read/write access for master profiles, in terms of DTOs."""

    async def create_full_profile(self, data: ProfileCreate) -> ProfileRead:
        """Persist a profile together with its experiences and skills.

        The whole aggregate is inserted in one flush; the returned
        :class:`ProfileRead` is re-read via :meth:`get_full_profile` so the
        children come back through the same ``selectinload`` path as a plain
        fetch (consistent shape, generated ids populated).
        """
        entity = MasterProfile(
            candidate_name=data.candidate_name,
            target_titles=data.target_titles,
            preferences=data.preferences,
            experiences=[
                ProfileExperience(**exp.model_dump()) for exp in data.experiences
            ],
            skills=[ProfileSkill(**skill.model_dump()) for skill in data.skills],
        )
        self._session.add(entity)
        await self._session.flush()

        profile = await self.get_full_profile(entity.id)
        if profile is None:  # unreachable: just flushed in this transaction
            raise RuntimeError(
                f"Profile {entity.id} not found immediately after flush — "
                "this is a bug."
            )
        return profile

    async def get_all_profiles(self) -> list[ProfileRead]:
        """Return every master profile with its children eagerly loaded.

        Uses the same ``selectinload`` path as :meth:`get_full_profile` (the
        async-safe pattern), so the sourcing task can read each profile's
        ``target_titles`` and ``preferences`` without tripping the ``lazy="raise"``
        guard on the relationships.
        """
        stmt = select(MasterProfile).options(
            selectinload(MasterProfile.experiences),
            selectinload(MasterProfile.skills),
        )
        entities = (await self._session.scalars(stmt)).all()
        return [ProfileRead.model_validate(entity) for entity in entities]

    async def get_full_profile(self, profile_id: uuid.UUID) -> ProfileRead | None:
        """Return the profile with all experiences and skills eagerly loaded.

        Uses ``selectinload`` so the children are fetched in separate batched
        queries (the async-safe pattern), then validated into a single nested
        :class:`ProfileRead`. Returns ``None`` if no such profile exists.
        """
        stmt = (
            select(MasterProfile)
            .where(MasterProfile.id == profile_id)
            .options(
                selectinload(MasterProfile.experiences),
                selectinload(MasterProfile.skills),
            )
        )
        entity = (await self._session.scalars(stmt)).first()
        return ProfileRead.model_validate(entity) if entity is not None else None
