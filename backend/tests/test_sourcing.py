"""Tests for the SerpAPI (Google Jobs) sourcing service.

HTTP is exercised through httpx's built-in :class:`httpx.MockTransport` (no new
dependency, no real network), with a client injected into the service so its
own client lifecycle is bypassed.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import SourcingSettings
from app.models.schemas.job import JobCreate
from app.services import sourcing
from app.services.sourcing import (
    SourcingError,
    _to_job_create,
    fetch_jobs_from_google,
)


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> SourcingSettings:
    """Bypass the fail-fast SERPAPI_KEY requirement with an explicit test config.

    The key is provided via its env alias (SERPAPI_KEY) — pydantic-settings
    populates ``validation_alias`` fields from the environment, not from
    field-name init kwargs.
    """
    monkeypatch.setenv("SERPAPI_KEY", "test-key")
    settings = SourcingSettings()
    monkeypatch.setattr(sourcing, "get_sourcing_settings", lambda: settings)
    return settings


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_happy_path_returns_jobs_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["engine"] == "google_jobs"
        assert request.url.params["q"] == "AI Engineer"
        assert request.url.params["location"] == "Berlin"
        assert request.url.params["api_key"] == "test-key"
        return httpx.Response(200, json={"jobs_results": [{"job_id": "1"}]})

    async with _client(handler) as client:
        results = await fetch_jobs_from_google("AI Engineer", "Berlin", client=client)

    assert results == [{"job_id": "1"}]


async def test_fetch_follows_next_page_token() -> None:
    pages = {
        None: {
            "jobs_results": [{"job_id": "1"}],
            "serpapi_pagination": {"next_page_token": "tok2"},
        },
        "tok2": {
            "jobs_results": [{"job_id": "2"}],
            "serpapi_pagination": {"next_page_token": "tok3"},
        },
        "tok3": {"jobs_results": [{"job_id": "3"}]},  # no further token
    }

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.url.params.get("next_page_token")
        return httpx.Response(200, json=pages[token])

    async with _client(handler) as client:
        results = await fetch_jobs_from_google("Eng", "NYC", client=client)

    assert [j["job_id"] for j in results] == ["1", "2", "3"]


async def test_fetch_stops_at_max_pages() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        # Always advertise another page; max_pages must still cap us.
        return httpx.Response(
            200,
            json={
                "jobs_results": [{"job_id": str(calls)}],
                "serpapi_pagination": {"next_page_token": f"tok{calls}"},
            },
        )

    async with _client(handler) as client:
        results = await fetch_jobs_from_google("Eng", "NYC", client=client, max_pages=2)

    assert calls == 2
    assert len(results) == 2


async def test_fetch_http_500_raises_sourcing_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    async with _client(handler) as client:
        with pytest.raises(SourcingError):
            await fetch_jobs_from_google("Eng", "NYC", client=client)


async def test_fetch_timeout_raises_sourcing_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    async with _client(handler) as client:
        with pytest.raises(SourcingError):
            await fetch_jobs_from_google("Eng", "NYC", client=client)


async def test_fetch_connection_error_raises_sourcing_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    async with _client(handler) as client:
        with pytest.raises(SourcingError):
            await fetch_jobs_from_google("Eng", "NYC", client=client)


# --------------------------------------------------------------------------- #
# _to_job_create mapping                                                       #
# --------------------------------------------------------------------------- #
def test_to_job_create_prefers_share_link() -> None:
    job = _to_job_create(
        {
            "job_id": "abc",
            "title": "Senior Engineer",
            "company_name": "Acme",
            "description": "Do things.",
            "share_link": "https://g.co/share",
            "apply_options": [{"link": "https://apply.example/1"}],
        }
    )
    assert isinstance(job, JobCreate)
    assert job.source_job_id == "abc"
    assert job.source_url == "https://g.co/share"
    assert job.company_name == "Acme"


def test_to_job_create_falls_back_to_apply_option_then_synthetic() -> None:
    apply_only = _to_job_create(
        {"job_id": "x", "title": "T", "apply_options": [{"link": "https://apply/2"}]}
    )
    assert apply_only is not None
    assert apply_only.source_url == "https://apply/2"

    synthetic = _to_job_create({"job_id": "y", "title": "T"})
    assert synthetic is not None
    assert synthetic.source_url == "google_jobs://y"
    # min_length=1 fields get non-empty fallbacks.
    assert synthetic.company_name == "Unknown"
    assert synthetic.description == "No description provided."


def test_to_job_create_skips_result_without_job_id() -> None:
    assert _to_job_create({"title": "No id"}) is None
