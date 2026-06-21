"""FastAPI router for job postings.

Demonstrates the access rule: endpoints depend on a :class:`JobRepository`
(which itself depends on the request-scoped session) and never touch the
``AsyncSession`` directly. Maps the contract from API_Contracts.md.
"""

from __future__ import annotations

import base64
import binascii
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, status
from googleapiclient.errors import HttpError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_outreach_settings
from app.core.logging import get_logger
from app.db.database import get_session
from app.models.enums import JobStatus
from app.models.schemas.job import JobCreate, JobMatchResponse, JobRead, JobUpdate
from app.models.schemas.outreach import OutreachSendRequest, OutreachSendResponse
from app.repositories.job_repository import JobRepository
from app.services.gmail_client import GmailClient, get_gmail_client
from app.services.outreach import append_engineering_disclaimer
from app.services.orchestrator import (
    JobNotFoundError,
    ProfileNotFoundError,
    PipelineDegradedError,
    PipelineExecutionError,
    match_and_save,
    run_pipeline_stream,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def get_job_repository(
    session: AsyncSession = Depends(get_session),
) -> JobRepository:
    """Provide a repository bound to the request-scoped session."""
    return JobRepository(session)


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreate,
    repo: JobRepository = Depends(get_job_repository),
) -> JobRead:
    """Add a new job posting."""
    return await repo.create(payload)


@router.get("", response_model=list[JobRead])
async def list_jobs(
    job_status: JobStatus,
    repo: JobRepository = Depends(get_job_repository),
) -> list[JobRead]:
    """List job postings filtered by status (``?job_status=NEW``)."""
    return await repo.get_by_status(job_status)


@router.get("/{job_id}", response_model=JobRead)
async def get_job(
    job_id: uuid.UUID,
    repo: JobRepository = Depends(get_job_repository),
) -> JobRead:
    """Fetch a single posting by id."""
    job = await repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job posting not found")
    return job


@router.patch("/{job_id}", response_model=JobRead)
async def update_job_status_and_score(
    job_id: uuid.UUID,
    payload: JobUpdate,
    repo: JobRepository = Depends(get_job_repository),
) -> JobRead:
    """Update a posting's status and/or match score."""
    job = await repo.update_status_and_score(job_id, payload)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job posting not found")
    return job


@router.post("/{job_id}/match", response_model=JobMatchResponse)
async def match_job(
    job_id: uuid.UUID,
    profile_id: uuid.UUID = Query(...),
    session: AsyncSession = Depends(get_session),
) -> JobMatchResponse:
    """Run the AI matching pipeline for a job and profile, save results to DB.

    Query parameters:
        profile_id: UUID of the candidate profile to match against the job.

    Returns:
        The updated job posting with match score, cover letter draft, and status.

    Raises:
        404: If job_id or profile_id does not exist in the database.
        422: If AI pipeline execution fails.
        503: If the model is unavailable (quota) and produced no verdict.
    """
    try:
        job = await match_and_save(job_id, profile_id, session)
    except JobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"job posting {job_id} not found",
        )
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"profile {profile_id} not found",
        )
    except PipelineDegradedError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI evaluation/generation is unavailable (model quota). Try again later.",
        )
    except PipelineExecutionError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AI pipeline execution failed. Please try again later.",
        )

    return JobMatchResponse.model_validate(job)


@router.post("/{job_id}/outreach/send", response_model=OutreachSendResponse)
async def send_outreach_email(
    job_id: uuid.UUID,
    payload: OutreachSendRequest,
    repo: JobRepository = Depends(get_job_repository),
    gmail: GmailClient = Depends(get_gmail_client),
) -> OutreachSendResponse:
    """Send a cold-outreach email for a posting via the Gmail API.

    The ``job_id`` scopes the action to a real posting (404 if unknown). The body
    carries the recipient, subject, and text — typically pre-filled from the
    recruiter contact resolved during matching.

    Raises:
        404: If ``job_id`` does not exist.
        500: If Gmail rejects the send or OAuth/credentials are unavailable.
    """
    job = await repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job posting not found")

    # Decode the optional attachment (e.g. the tailored-CV PDF) up front so a
    # malformed payload is a clean 400, not a 500 from inside the Gmail call.
    attachment_bytes: bytes | None = None
    if payload.attachment_content_base64:
        try:
            attachment_bytes = base64.b64decode(
                payload.attachment_content_base64, validate=True
            )
        except (binascii.Error, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="attachment_content_base64 is not valid base64.",
            )

    # Append the engineering-disclaimer postscript to every recruiter email. Done
    # here (the single send seam) so the disclaimer is guaranteed regardless of the
    # body the client sent; the helper is idempotent, so a re-send never doubles it.
    body_text = append_engineering_disclaimer(
        payload.body, github_url=get_outreach_settings().github_url
    )

    try:
        result = await gmail.send_email(
            to_email=str(payload.to_email),
            subject=payload.subject,
            body_text=body_text,
            attachment_filename=payload.attachment_filename,
            attachment_bytes=attachment_bytes,
        )
    except HttpError as exc:
        # Gmail API-level failure (bad request, quota, auth scope, etc.).
        logger.error(
            "outreach_send_failed",
            extra={"job_id": str(job_id), "status_code": exc.status_code},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send the email via Gmail. Please try again later.",
        )
    except Exception:  # noqa: BLE001 — missing credentials / OAuth / refresh errors
        # Not an HttpError (e.g. credentials.json missing, consent failed): still
        # surface a clean 500 rather than leaking a stack trace to the client.
        logger.exception(
            "outreach_send_error", extra={"job_id": str(job_id)}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Outreach email could not be sent (mail service unavailable).",
        )

    return OutreachSendResponse(
        status="sent",
        message_id=result.get("id"),
        to_email=payload.to_email,
    )


@router.websocket("/{job_id}/ws-match")
async def match_job_ws(
    websocket: WebSocket,
    job_id: uuid.UUID,
    profile_id: uuid.UUID = Query(...),
) -> None:
    """Stream the AI matching pipeline for a job/profile over a WebSocket.

    Query parameters:
        profile_id: UUID of the candidate profile to match against the job.

    Accepts the connection, then delegates to
    :func:`~app.services.orchestrator.run_pipeline_stream`, which emits one JSON
    frame per pipeline stage (``init`` → per-node progress, with ``match_profile``
    carrying the score and reason → a final ``done``/``error``) and closes the
    socket. Missing job/profile, pipeline errors, and client disconnects are all
    handled inside that function.

    Unlike the REST routes, this endpoint does *not* depend on ``get_session``:
    the streaming service owns its own short-lived sessions so no database
    connection is pinned for the whole (long) graph run, and there is no
    request-scoped commit to collide with the service's own.
    """
    await websocket.accept()
    # run_pipeline_stream already handles disconnects, pipeline errors, and
    # persistence failures internally, but guard the endpoint as a last resort so
    # no unexpected error can ever escape into the ASGI server.
    try:
        await run_pipeline_stream(job_id, profile_id, websocket)
    except Exception:  # noqa: BLE001 — endpoint must never crash the server
        logger.exception(
            "match_job_ws_failed",
            extra={"job_id": str(job_id), "profile_id": str(profile_id)},
        )
