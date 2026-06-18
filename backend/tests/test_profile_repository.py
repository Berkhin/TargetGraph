"""Contract tests for ProfileRepository (in-memory async SQLite)."""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas.profile import (
    ExperienceCreate,
    ExperienceRead,
    ProfileCreate,
    ProfileRead,
    ProfileUpdate,
    SkillCreate,
    SkillRead,
)
from app.models.sql.profile import MasterProfile, ProfileExperience, ProfileSkill
from app.repositories.profile_repository import ProfileRepository


def _new_profile(name: str = "EVGENIY BERKHIN") -> ProfileCreate:
    return ProfileCreate(
        candidate_name=name,
        target_titles=["Full Stack Engineer", "AI Engineer"],
        preferences={"location": "Tel Aviv", "email": "berkhindev@gmail.com"},
        experiences=[
            ExperienceCreate(
                company="Siemens",
                role="AI & Full Stack Engineer",
                start_date=datetime.date(2024, 1, 1),
                end_date=None,
                highlights=["arch", "perf"],
            ),
            ExperienceCreate(
                company="Shield",
                role="Frontend Engineer",
                start_date=datetime.date(2022, 1, 1),
                end_date=datetime.date(2024, 1, 1),
                highlights=["components"],
            ),
        ],
        skills=[
            SkillCreate(category="Frontend", skills=["React", "TypeScript"]),
            SkillCreate(category="Languages", skills=["English", "Russian"]),
        ],
    )


async def test_create_full_profile_returns_nested_dto(session: AsyncSession) -> None:
    repo = ProfileRepository(session)
    created = await repo.create_full_profile(_new_profile())

    # Repository returns a DTO graph, never ORM objects.
    assert isinstance(created, ProfileRead)
    assert isinstance(created.id, uuid.UUID)
    assert created.candidate_name == "EVGENIY BERKHIN"
    assert created.target_titles == ["Full Stack Engineer", "AI Engineer"]
    assert created.preferences["location"] == "Tel Aviv"

    assert len(created.experiences) == 2
    assert len(created.skills) == 2
    assert all(isinstance(e, ExperienceRead) for e in created.experiences)
    assert all(isinstance(s, SkillRead) for s in created.skills)
    # Children carry server-generated ids.
    assert all(isinstance(e.id, uuid.UUID) for e in created.experiences)
    assert all(isinstance(s.id, uuid.UUID) for s in created.skills)


async def test_create_full_profile_persists_children(session: AsyncSession) -> None:
    repo = ProfileRepository(session)
    created = await repo.create_full_profile(_new_profile())

    # Children are actually rows in the DB, linked by FK to the profile.
    rows = (
        await session.scalars(
            select(ProfileExperience).where(
                ProfileExperience.profile_id == created.id
            )
        )
    ).all()
    assert {r.company for r in rows} == {"Siemens", "Shield"}


async def test_get_full_profile_round_trip(session: AsyncSession) -> None:
    repo = ProfileRepository(session)
    created = await repo.create_full_profile(_new_profile())

    fetched = await repo.get_full_profile(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.candidate_name == created.candidate_name

    # JSON columns round-trip as native Python containers.
    exp = next(e for e in fetched.experiences if e.company == "Siemens")
    assert exp.highlights == ["arch", "perf"]
    assert exp.end_date is None
    skill = next(s for s in fetched.skills if s.category == "Frontend")
    assert skill.skills == ["React", "TypeScript"]


async def test_get_full_profile_missing_returns_none(session: AsyncSession) -> None:
    repo = ProfileRepository(session)
    assert await repo.get_full_profile(uuid.uuid4()) is None


async def test_lazy_relationship_access_raises(session: AsyncSession) -> None:
    """lazy='raise' turns an accidental lazy load into an immediate, clear error.

    Fetching a profile WITHOUT selectinload and then touching .experiences must
    raise rather than silently emit a query (which under asyncio surfaces as a
    cryptic MissingGreenlet far from the cause).
    """
    repo = ProfileRepository(session)
    created = await repo.create_full_profile(_new_profile())
    session.expunge_all()  # drop the instance whose collections are already loaded

    entity = await session.get(MasterProfile, created.id)  # no selectinload
    assert entity is not None
    with pytest.raises(InvalidRequestError):
        _ = entity.experiences
    with pytest.raises(InvalidRequestError):
        _ = entity.skills


async def test_get_all_profiles_returns_all_with_children(
    session: AsyncSession,
) -> None:
    repo = ProfileRepository(session)
    await repo.create_full_profile(_new_profile(name="Alice"))
    await repo.create_full_profile(_new_profile(name="Bob"))

    profiles = await repo.get_all_profiles()
    assert {p.candidate_name for p in profiles} == {"Alice", "Bob"}
    # Children are eagerly loaded (no lazy='raise' surprises for the task).
    for profile in profiles:
        assert len(profile.experiences) == 2
        assert len(profile.skills) == 2
        assert profile.preferences["location"] == "Tel Aviv"


async def test_get_all_profiles_empty(session: AsyncSession) -> None:
    repo = ProfileRepository(session)
    assert await repo.get_all_profiles() == []


async def test_get_first_profile_empty_returns_none(session: AsyncSession) -> None:
    repo = ProfileRepository(session)
    assert await repo.get_first_profile() is None


async def test_get_first_profile_is_deterministic_with_children(
    session: AsyncSession,
) -> None:
    repo = ProfileRepository(session)
    await repo.create_full_profile(_new_profile(name="Alice"))
    await repo.create_full_profile(_new_profile(name="Bob"))

    first = await repo.get_first_profile()
    assert first is not None
    # Stable across calls (ordered by id), and children are eagerly loaded.
    again = await repo.get_first_profile()
    assert again is not None
    assert first.id == again.id
    assert len(first.experiences) == 2
    assert len(first.skills) == 2


async def test_empty_children_default_to_lists(session: AsyncSession) -> None:
    repo = ProfileRepository(session)
    created = await repo.create_full_profile(
        ProfileCreate(candidate_name="No Children")
    )
    assert created.target_titles == []
    assert created.preferences == {}
    assert created.experiences == []
    assert created.skills == []


async def test_update_full_profile_replaces_scalars_and_children(
    session: AsyncSession,
) -> None:
    repo = ProfileRepository(session)
    created = await repo.create_full_profile(_new_profile())
    old_exp_ids = {e.id for e in created.experiences}

    updated = await repo.update_full_profile(
        created.id,
        ProfileUpdate(
            candidate_name="ADA LOVELACE",
            target_titles=["Researcher"],
            preferences={"location": "London"},
            experiences=[
                ExperienceCreate(
                    company="Analytical Engine",
                    role="Mathematician",
                    start_date=datetime.date(1843, 1, 1),
                    end_date=None,
                    highlights=["first algorithm"],
                )
            ],
            skills=[SkillCreate(category="Math", skills=["Algorithms"])],
        ),
    )

    assert updated is not None
    assert updated.id == created.id  # same aggregate, replaced in place
    assert updated.candidate_name == "ADA LOVELACE"
    assert updated.target_titles == ["Researcher"]
    assert updated.preferences == {"location": "London"}

    # Children fully replaced: one new experience/skill, none of the old ids.
    assert len(updated.experiences) == 1
    assert updated.experiences[0].company == "Analytical Engine"
    assert len(updated.skills) == 1
    assert updated.skills[0].category == "Math"
    assert old_exp_ids.isdisjoint({e.id for e in updated.experiences})

    # The old child rows are gone from the table, not just detached.
    exp_rows = (
        await session.scalars(
            select(ProfileExperience).where(
                ProfileExperience.profile_id == created.id
            )
        )
    ).all()
    assert {r.company for r in exp_rows} == {"Analytical Engine"}
    skill_rows = (
        await session.scalars(
            select(ProfileSkill).where(ProfileSkill.profile_id == created.id)
        )
    ).all()
    assert {r.category for r in skill_rows} == {"Math"}


async def test_update_full_profile_can_clear_children(session: AsyncSession) -> None:
    repo = ProfileRepository(session)
    created = await repo.create_full_profile(_new_profile())

    updated = await repo.update_full_profile(
        created.id,
        ProfileUpdate(candidate_name="Solo", target_titles=[], preferences={}),
    )
    assert updated is not None
    assert updated.experiences == []
    assert updated.skills == []


async def test_update_full_profile_missing_returns_none(
    session: AsyncSession,
) -> None:
    repo = ProfileRepository(session)
    result = await repo.update_full_profile(
        uuid.uuid4(), ProfileUpdate(candidate_name="Nobody")
    )
    assert result is None
