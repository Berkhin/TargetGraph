"""Endpoint tests for the profiles router.

Exercises the ASGI app end-to-end via httpx's in-process transport, with the
request-scoped ``get_session`` dependency overridden to use the in-memory
SQLite session from ``conftest`` (no live Postgres needed). Repository logic is
covered separately in ``test_profile_repository``; here we assert the HTTP
contract: routing, status codes, and response shape.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.main import app
from app.models.schemas.profile import ProfileCreate, SkillCreate
from app.repositories.profile_repository import ProfileRepository


@pytest.fixture
def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """An httpx client wired to the app, sharing the test's SQLite session."""

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_profiles_empty(client: AsyncClient) -> None:
    async with client:
        resp = await client.get("/api/v1/profiles")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_and_active_profile(
    client: AsyncClient, session: AsyncSession
) -> None:
    repo = ProfileRepository(session)
    created = await repo.create_full_profile(
        ProfileCreate(candidate_name="Ada Lovelace", target_titles=["Engineer"])
    )

    async with client:
        list_resp = await client.get("/api/v1/profiles")
        active_resp = await client.get("/api/v1/profiles/active")

    assert list_resp.status_code == 200
    body = list_resp.json()
    assert len(body) == 1
    assert body[0]["candidate_name"] == "Ada Lovelace"
    assert body[0]["id"] == str(created.id)

    assert active_resp.status_code == 200
    assert active_resp.json()["id"] == str(created.id)


@pytest.mark.asyncio
async def test_active_profile_404_when_none(client: AsyncClient) -> None:
    async with client:
        resp = await client.get("/api/v1/profiles/active")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_profile_replaces_aggregate(
    client: AsyncClient, session: AsyncSession
) -> None:
    repo = ProfileRepository(session)
    created = await repo.create_full_profile(
        ProfileCreate(
            candidate_name="Ada Lovelace",
            target_titles=["Engineer"],
            skills=[SkillCreate(category="Math", skills=["Algorithms"])],
        )
    )

    payload = {
        "candidate_name": "Ada L.",
        "target_titles": ["Researcher", "Author"],
        "preferences": {"location": "London"},
        "experiences": [
            {
                "company": "Analytical Engine",
                "role": "Mathematician",
                "highlights": ["first algorithm"],
                "start_date": "1843-01-01",
                "end_date": None,
            }
        ],
        "skills": [{"category": "Math", "skills": ["Algorithms", "Logic"]}],
    }

    async with client:
        resp = await client.put(f"/api/v1/profiles/{created.id}", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(created.id)
    assert body["candidate_name"] == "Ada L."
    assert body["target_titles"] == ["Researcher", "Author"]
    assert body["preferences"] == {"location": "London"}
    assert len(body["experiences"]) == 1
    assert body["experiences"][0]["company"] == "Analytical Engine"
    assert body["skills"][0]["skills"] == ["Algorithms", "Logic"]


@pytest.mark.asyncio
async def test_update_profile_404_when_missing(client: AsyncClient) -> None:
    async with client:
        resp = await client.put(
            f"/api/v1/profiles/{uuid.uuid4()}",
            json={"candidate_name": "Ghost"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_profile_422_on_invalid_payload(
    client: AsyncClient, session: AsyncSession
) -> None:
    repo = ProfileRepository(session)
    created = await repo.create_full_profile(
        ProfileCreate(candidate_name="Ada Lovelace")
    )

    async with client:
        # candidate_name violates min_length=1.
        resp = await client.put(
            f"/api/v1/profiles/{created.id}", json={"candidate_name": ""}
        )
    assert resp.status_code == 422
