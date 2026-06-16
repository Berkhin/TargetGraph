"""Tests for the Apify (LinkedIn Jobs) sourcing service.

Apify is exercised through a hand-rolled fake :class:`ApifyClientAsync` injected
into the service (no real network, no real container runs), so we assert the
run_input we send, the dataset we read back, error wrapping, and the mapper.
"""

from __future__ import annotations

import pytest

from app.core.config import SourcingSettings
from app.models.schemas.job import JobCreate
from app.services import sourcing
from app.services.sourcing import (
    SourcingError,
    _to_job_create,
    fetch_jobs_from_apify,
)


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> SourcingSettings:
    """Bypass the fail-fast APIFY_TOKEN requirement with an explicit test config.

    The token is provided via its env alias (APIFY_TOKEN) — pydantic-settings
    populates ``validation_alias`` fields from the environment, not from
    field-name init kwargs.
    """
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    settings = SourcingSettings()
    monkeypatch.setattr(sourcing, "get_sourcing_settings", lambda: settings)
    return settings


# --------------------------------------------------------------------------- #
# Fake ApifyClientAsync                                                        #
# --------------------------------------------------------------------------- #
class _FakeListPage:
    def __init__(self, items: list[dict]) -> None:
        self.items = items


class _FakeDatasetClient:
    def __init__(self, items: list[dict]) -> None:
        self._items = items

    async def list_items(self) -> _FakeListPage:
        return _FakeListPage(self._items)


class _FakeActorClient:
    def __init__(self, run: dict | None, error: Exception | None) -> None:
        self._run = run
        self._error = error
        self.run_inputs: list[dict] = []

    async def call(self, *, run_input: dict | None = None) -> dict | None:
        self.run_inputs.append(run_input or {})
        if self._error is not None:
            raise self._error
        return self._run


class _FakeApifyClient:
    """Minimal stand-in for ApifyClientAsync covering actor().call() + dataset()."""

    _DEFAULT_RUN = object()  # sentinel: distinguish "not given" from explicit None

    def __init__(
        self,
        *,
        run: dict | None = _DEFAULT_RUN,
        items: list[dict] | None = None,
        actor_error: Exception | None = None,
    ) -> None:
        self._run = (
            {"status": "SUCCEEDED", "defaultDatasetId": "ds1"}
            if run is self._DEFAULT_RUN
            else run
        )
        self._items = items or []
        self._actor_error = actor_error
        self.actor_calls: list[str] = []
        self.dataset_ids: list[str] = []
        self.actor_client = _FakeActorClient(self._run, actor_error)

    def actor(self, actor_id: str) -> _FakeActorClient:
        self.actor_calls.append(actor_id)
        return self.actor_client

    def dataset(self, dataset_id: str) -> _FakeDatasetClient:
        self.dataset_ids.append(dataset_id)
        return _FakeDatasetClient(self._items)


async def test_fetch_happy_path_returns_dataset_items() -> None:
    items = [{"job_id": "1"}, {"job_id": "2"}]
    client = _FakeApifyClient(items=items)

    results = await fetch_jobs_from_apify(
        '"AI Engineer" OR "ML Engineer"', "Berlin", client=client
    )

    assert results == items
    # The whole profile is one actor run against the configured actor.
    assert client.actor_calls == ["curious_coder/linkedin-jobs-scraper"]
    assert client.dataset_ids == ["ds1"]


async def test_fetch_sends_expected_run_input() -> None:
    client = _FakeApifyClient(items=[])

    await fetch_jobs_from_apify('"Eng"', "Israel", client=client)

    # The actor is URL-driven: the (query, location) pair is encoded into a
    # LinkedIn guest search URL passed as the required ``urls`` input, and the
    # cost-bounding ``pages`` setting (default 1) is translated into ``count``.
    assert client.actor_client.run_inputs == [
        {
            "urls": [
                "https://www.linkedin.com/jobs/search/"
                "?keywords=%22Eng%22&location=Israel"
            ],
            "count": 25,
            "scrapeCompany": False,
        }
    ]


async def test_fetch_actor_error_raises_sourcing_error() -> None:
    client = _FakeApifyClient(actor_error=RuntimeError("actor exploded"))

    with pytest.raises(SourcingError):
        await fetch_jobs_from_apify('"Eng"', "NYC", client=client)


async def test_fetch_missing_dataset_raises_sourcing_error() -> None:
    # A run that finished without a dataset id is treated as a failure.
    client = _FakeApifyClient(run={"status": "SUCCEEDED", "defaultDatasetId": None})

    with pytest.raises(SourcingError):
        await fetch_jobs_from_apify('"Eng"', "NYC", client=client)


async def test_fetch_none_run_raises_sourcing_error() -> None:
    client = _FakeApifyClient(run=None)

    with pytest.raises(SourcingError):
        await fetch_jobs_from_apify('"Eng"', "NYC", client=client)


# --------------------------------------------------------------------------- #
# _to_job_create mapping                                                       #
# --------------------------------------------------------------------------- #
def test_to_job_create_maps_apify_keys() -> None:
    job = _to_job_create(
        {
            "job_id": "abc",
            "job_title": "Senior Engineer",
            "company": "Acme",
            "description": "Do things.",
            "job_url": "https://www.linkedin.com/jobs/view/abc",
        }
    )
    assert isinstance(job, JobCreate)
    assert job.source_job_id == "abc"
    assert job.job_title == "Senior Engineer"
    assert job.company_name == "Acme"
    assert job.description == "Do things."
    assert job.source_url == "https://www.linkedin.com/jobs/view/abc"


def test_to_job_create_coerces_numeric_job_id_and_falls_back_to_synthetic_url() -> None:
    # LinkedIn job ids arrive as numbers; they must coerce to str cleanly, and a
    # missing job_url falls back to a synthetic, dedup-stable URL.
    job = _to_job_create({"job_id": 4055123, "job_title": "T"})
    assert job is not None
    assert job.source_job_id == "4055123"
    assert job.source_url == "apify://4055123"
    # min_length=1 fields get non-empty fallbacks.
    assert job.company_name == "Unknown"
    assert job.description == "No description provided."


def test_to_job_create_skips_result_without_job_id() -> None:
    assert _to_job_create({"job_title": "No id"}) is None
