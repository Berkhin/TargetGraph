"""Endpoint tests for the cold-outreach send route.

Exercises ``POST /api/v1/jobs/{job_id}/outreach/send`` via httpx's in-process
transport. The DB ``get_session`` dependency is overridden with the in-memory
SQLite session (as in ``test_profiles_api``), and ``get_gmail_client`` is
overridden with a fake so no real OAuth / Gmail traffic happens.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from googleapiclient.errors import HttpError
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.main import app
from app.models.schemas.job import JobCreate
from app.repositories.job_repository import JobRepository
from app.services.gmail_client import get_gmail_client


class _FakeGmailClient:
    """Stand-in for GmailClient: records sends, returns canned result or raises."""

    def __init__(self, *, result: dict | None = None, error: Exception | None = None):
        self._result = result if result is not None else {"id": "msg-123"}
        self._error = error
        self.calls: list[tuple[str, str, str]] = []
        # Records (filename, bytes) of the attachment passed on the last send.
        self.attachments: list[tuple[str | None, bytes | None]] = []

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        *,
        attachment_filename: str | None = None,
        attachment_bytes: bytes | None = None,
    ) -> dict:
        self.calls.append((to_email, subject, body_text))
        self.attachments.append((attachment_filename, attachment_bytes))
        if self._error is not None:
            raise self._error
        return self._result


def _wire(session: AsyncSession, gmail: _FakeGmailClient) -> AsyncClient:
    """Build an httpx client with the session + gmail dependencies overridden."""

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_gmail_client] = lambda: gmail
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def _make_job(session: AsyncSession) -> uuid.UUID:
    job = await JobRepository(session).create(
        JobCreate(
            company_name="Acme",
            job_title="Engineer",
            description="Build things",
            source_url="https://example.com/jobs/1",
        )
    )
    return job.id


@pytest.mark.asyncio
async def test_send_outreach_success(session: AsyncSession) -> None:
    job_id = await _make_job(session)
    gmail = _FakeGmailClient(result={"id": "abc-789"})
    client = _wire(session, gmail)
    try:
        async with client:
            resp = await client.post(
                f"/api/v1/jobs/{job_id}/outreach/send",
                json={
                    "to_email": "recruiter@acme.com",
                    "subject": "Hello",
                    "body": "Dear Michal, ...",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json() == {
        "status": "sent",
        "message_id": "abc-789",
        "to_email": "recruiter@acme.com",
    }
    assert gmail.calls == [("recruiter@acme.com", "Hello", "Dear Michal, ...")]


@pytest.mark.asyncio
async def test_send_outreach_with_attachment_decodes_base64(
    session: AsyncSession,
) -> None:
    import base64

    job_id = await _make_job(session)
    gmail = _FakeGmailClient()
    client = _wire(session, gmail)
    raw = b"%PDF-1.4 fake cv bytes"
    try:
        async with client:
            resp = await client.post(
                f"/api/v1/jobs/{job_id}/outreach/send",
                json={
                    "to_email": "recruiter@acme.com",
                    "subject": "Hello",
                    "body": "Dear Michal, ...",
                    "attachment_filename": "cv.pdf",
                    "attachment_content_base64": base64.b64encode(raw).decode(),
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    # The backend decoded the base64 and passed the raw bytes + filename through.
    assert gmail.attachments == [("cv.pdf", raw)]


@pytest.mark.asyncio
async def test_send_outreach_400_on_bad_base64(session: AsyncSession) -> None:
    job_id = await _make_job(session)
    gmail = _FakeGmailClient()
    client = _wire(session, gmail)
    try:
        async with client:
            resp = await client.post(
                f"/api/v1/jobs/{job_id}/outreach/send",
                json={
                    "to_email": "recruiter@acme.com",
                    "subject": "Hello",
                    "body": "Hi",
                    "attachment_filename": "cv.pdf",
                    "attachment_content_base64": "!!! not base64 !!!",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert gmail.calls == []  # never attempted to send a malformed attachment


@pytest.mark.asyncio
async def test_send_outreach_404_for_unknown_job(session: AsyncSession) -> None:
    gmail = _FakeGmailClient()
    client = _wire(session, gmail)
    try:
        async with client:
            resp = await client.post(
                f"/api/v1/jobs/{uuid.uuid4()}/outreach/send",
                json={"to_email": "x@acme.com", "subject": "Hi", "body": "Hi"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404
    assert gmail.calls == []  # never attempted a send for a missing job


@pytest.mark.asyncio
async def test_send_outreach_500_on_gmail_httperror(session: AsyncSession) -> None:
    job_id = await _make_job(session)

    class _Resp:
        status = 403
        reason = "Forbidden"

    gmail = _FakeGmailClient(error=HttpError(_Resp(), b'{"error": "denied"}'))
    client = _wire(session, gmail)
    try:
        async with client:
            resp = await client.post(
                f"/api/v1/jobs/{job_id}/outreach/send",
                json={"to_email": "x@acme.com", "subject": "Hi", "body": "Hi"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_send_outreach_422_on_invalid_email(session: AsyncSession) -> None:
    job_id = await _make_job(session)
    gmail = _FakeGmailClient()
    client = _wire(session, gmail)
    try:
        async with client:
            resp = await client.post(
                f"/api/v1/jobs/{job_id}/outreach/send",
                json={"to_email": "not-an-email", "subject": "Hi", "body": "Hi"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422
    assert gmail.calls == []
