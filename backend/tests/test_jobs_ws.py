"""Tests for the streaming matching pipeline (``run_pipeline_stream``).

These exercise the service-layer orchestrator directly — the same philosophy as
``test_service.py`` — rather than driving a live WebSocket. A
:class:`_FakeWebSocket` records frames and models the two ways a connection
breaks (a ``receive()`` that raises ``WebSocketDisconnect``, and a ``send()``
that raises an arbitrary transport error), the compiled graph is monkeypatched
with a deterministic :class:`_FakeGraph`, and persistence runs against a shared
in-memory SQLite ``factory`` (``StaticPool``) — exactly like ``run_sourcing_job``
is tested, since the service now owns its own short-lived sessions.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

import app.models.sql  # noqa: F401 - registers tables on Base.metadata
from app.db.base import Base
from app.models.enums import JobStatus
from app.models.schemas.job import JobCreate
from app.models.schemas.profile import ProfileCreate
from app.repositories.job_repository import JobRepository
from app.repositories.profile_repository import ProfileRepository
from app.services import orchestrator as orchestrator_module
from app.services.orchestrator import run_pipeline_stream


# --------------------------------------------------------------------------- #
# Test doubles                                                                 #
# --------------------------------------------------------------------------- #
class _FakeWebSocket:
    """Records sent frames and models a broken connection two ways.

    * ``disconnect=True`` makes ``receive()`` mirror Starlette's *real* behaviour:
      the first call RETURNS ``{"type": "websocket.disconnect"}`` (it does NOT
      raise), and a *second* call raises ``RuntimeError`` — exactly the trap the
      disconnect watcher has to survive. (The old fake raised
      ``WebSocketDisconnect`` on the first call, which hid the bug entirely.)
    * ``send_error`` makes ``send_json`` raise the given exception — how a dead
      socket surfaces on a ``send``-only path, with a server-dependent type that
      is often *not* ``WebSocketDisconnect``.
    """

    def __init__(
        self, *, disconnect: bool = False, send_error: BaseException | None = None
    ) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self._disconnect = disconnect
        self._disconnected = False
        self._send_error = send_error

    async def send_json(self, data: dict[str, Any]) -> None:
        if self._send_error is not None:
            raise self._send_error
        self.sent.append(data)

    async def receive(self) -> dict[str, Any]:
        if self._disconnect:
            # Mirror Starlette: first receive returns the disconnect message and
            # flips the socket to DISCONNECTED; a second receive raises.
            if self._disconnected:
                raise RuntimeError(
                    'Cannot call "receive" once a disconnect message has been received.'
                )
            self._disconnected = True
            return {"type": "websocket.disconnect", "code": 1001}
        await asyncio.sleep(3600)  # healthy client: block until the watcher is cancelled
        return {}  # pragma: no cover

    async def close(self, code: int = 1000) -> None:
        self.closed = True


class _FakeGraph:
    """Replays a fixed list of ``astream_events`` frames, yielding to the loop.

    The ``await asyncio.sleep(0)`` between frames is load-bearing for the
    disconnect test: it gives the concurrently-scheduled disconnect watcher a
    chance to run, matching how the real (awaiting) graph cedes control.
    """

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    async def astream_events(
        self, initial_state: dict[str, Any], version: str
    ) -> AsyncIterator[dict[str, Any]]:
        for event in self._events:
            await asyncio.sleep(0)
            yield event


def _node_end(name: str, output: dict[str, Any]) -> dict[str, Any]:
    """Shape one ``on_chain_end`` event the way LangGraph's v2 stream does."""
    return {"event": "on_chain_end", "name": name, "data": {"output": output}}


def _graph_events(
    score: int,
    reason: str = "Strong fit",
    cover: str = "Dear hiring team,",
    cv: str = "# Ada Lovelace\n- Built async APIs",
) -> list[dict[str, Any]]:
    """A full happy-path event stream for one match run.

    Mirrors the parallel fan-out: both ``generate_cover_letter`` and
    ``generate_tailored_cv`` emit ``on_chain_end`` before ``reviewer``.
    """
    return [
        {"event": "on_chain_start", "name": "LangGraph", "data": {}},
        _node_end("extract_requirements", {"extracted_requirements": "..."}),
        _node_end("match_profile", {"match_score": score, "match_reasoning": reason}),
        _node_end("generate_cover_letter", {"cover_letter_draft": cover}),
        _node_end("generate_tailored_cv", {"tailored_cv": cv}),
        _node_end("reviewer", {"review_comments": []}),
        # Root graph end — name is NOT a pipeline node, so it must be ignored.
        _node_end("LangGraph", {"match_score": score}),
    ]


# --------------------------------------------------------------------------- #
# Fixtures / helpers                                                           #
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory over one shared in-memory SQLite DB (StaticPool)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    await engine.dispose()


@pytest.fixture
def patch_graph(monkeypatch: pytest.MonkeyPatch):
    """Return a setter that swaps the compiled graph for a scripted fake."""

    def _install(events: list[dict[str, Any]]) -> None:
        monkeypatch.setattr(orchestrator_module, "compiled_graph", _FakeGraph(events))

    return _install


async def _seed(factory: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert one job and one profile in their own session; return their ids."""
    async with factory() as session:
        job = await JobRepository(session).create(
            JobCreate(
                company_name="Acme",
                job_title="Backend Engineer",
                description="Build async APIs in Python.",
                source_url="https://example.com/jobs/1",
            )
        )
        profile = await ProfileRepository(session).create_full_profile(
            ProfileCreate(candidate_name="Ada Lovelace", target_titles=["Engineer"])
        )
        await session.commit()
        return job.id, profile.id


async def _get_job(factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID):
    async with factory() as session:
        return await JobRepository(session).get_by_id(job_id)


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #
async def test_high_score_streams_and_persists_match(factory, patch_graph) -> None:
    job_id, profile_id = await _seed(factory)
    patch_graph(_graph_events(score=85))
    ws = _FakeWebSocket()

    await run_pipeline_stream(job_id, profile_id, ws, session_factory=factory)

    steps = [frame["step"] for frame in ws.sent]
    assert steps[0] == "init"
    assert "match_profile" in steps
    assert steps[-1] == "done"
    assert ws.closed is True

    match_frame = next(f for f in ws.sent if f["step"] == "match_profile")
    assert match_frame["score"] == 85
    assert match_frame["reason"] == "Strong fit"

    done = ws.sent[-1]
    assert done["status"] == JobStatus.MATCHED.value
    assert done["score"] == 85
    assert done["cover_letter_draft"] == "Dear hiring team,"
    assert done["tailored_cv_draft"] == "# Ada Lovelace\n- Built async APIs"

    saved = await _get_job(factory, job_id)
    assert saved is not None
    assert saved.status is JobStatus.MATCHED
    assert saved.match_score == 85
    assert saved.cover_letter_draft == "Dear hiring team,"
    assert saved.tailored_cv_draft == "# Ada Lovelace\n- Built async APIs"


async def test_low_score_sends_rejection_reason(factory, patch_graph) -> None:
    job_id, profile_id = await _seed(factory)
    patch_graph(_graph_events(score=30, reason="Missing core hard skills"))
    ws = _FakeWebSocket()

    await run_pipeline_stream(job_id, profile_id, ws, session_factory=factory)

    # The reason reaches the client both at the match step and in the closer.
    match_frame = next(f for f in ws.sent if f["step"] == "match_profile")
    assert match_frame["score"] == 30
    assert match_frame["reason"] == "Missing core hard skills"

    done = ws.sent[-1]
    assert done["status"] == JobStatus.REJECTED_BY_AI.value
    assert done["reason"] == "Missing core hard skills"

    saved = await _get_job(factory, job_id)
    assert saved is not None
    assert saved.status is JobStatus.REJECTED_BY_AI


async def test_missing_job_sends_error(factory, patch_graph) -> None:
    _, profile_id = await _seed(factory)
    patch_graph(_graph_events(score=90))
    ws = _FakeWebSocket()

    await run_pipeline_stream(uuid.uuid4(), profile_id, ws, session_factory=factory)

    assert len(ws.sent) == 1
    assert ws.sent[0]["step"] == "error"
    assert ws.closed is True


async def test_missing_profile_sends_error(factory, patch_graph) -> None:
    job_id, _ = await _seed(factory)
    patch_graph(_graph_events(score=90))
    ws = _FakeWebSocket()

    await run_pipeline_stream(job_id, uuid.uuid4(), ws, session_factory=factory)

    assert ws.sent[0]["step"] == "error"
    assert ws.closed is True


async def test_client_disconnect_detected_via_receive(factory, patch_graph) -> None:
    # The realistic disconnect: the watcher's receive() RETURNS a disconnect
    # message (and a second receive would raise RuntimeError). Nothing must be
    # persisted and — critically — run_pipeline_stream must NOT let the watcher's
    # RuntimeError leak out of its finally.
    job_id, profile_id = await _seed(factory)
    patch_graph(_graph_events(score=95))
    ws = _FakeWebSocket(disconnect=True)

    # Must complete without raising (regression guard for the leaking finally).
    await run_pipeline_stream(job_id, profile_id, ws, session_factory=factory)

    saved = await _get_job(factory, job_id)
    assert saved is not None
    assert saved.status is JobStatus.NEW  # untouched
    assert saved.match_score is None


async def test_send_failure_is_swallowed(factory, patch_graph) -> None:
    # A dead socket surfaces on send() as an arbitrary, non-WebSocketDisconnect
    # error. It must be caught, results must NOT be persisted, and the server
    # must survive (the broad cleanup in B2).
    job_id, profile_id = await _seed(factory)
    patch_graph(_graph_events(score=95))
    ws = _FakeWebSocket(send_error=RuntimeError("connection closed abruptly"))

    await run_pipeline_stream(job_id, profile_id, ws, session_factory=factory)

    assert ws.closed is True  # _safe_error still closed the socket
    saved = await _get_job(factory, job_id)
    assert saved is not None
    assert saved.status is JobStatus.NEW  # streaming failed before any save


async def test_graph_failure_sends_error_and_survives(
    factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id, profile_id = await _seed(factory)

    class _BoomGraph:
        async def astream_events(self, initial_state, version):  # noqa: ANN001
            raise RuntimeError("LLM exploded")
            yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(orchestrator_module, "compiled_graph", _BoomGraph())
    ws = _FakeWebSocket()

    await run_pipeline_stream(job_id, profile_id, ws, session_factory=factory)

    assert ws.sent[-1]["step"] == "error"
    assert ws.closed is True
    saved = await _get_job(factory, job_id)
    assert saved is not None
    assert saved.status is JobStatus.NEW
