"""Service-layer orchestrator: prepares inputs and drives the matching graph.

Architecture note — *Service Layer* boundary:

The LangGraph pipeline (``app.ai.orchestrator.compiled_graph``) is deliberately
DB-agnostic. It only knows about plain text (``job_text`` / ``profile_text``).
This module is the seam between persistence and AI: it reads the job and profile
through their repositories, renders them into the text the graph expects, runs
the graph, and hands back the final state.

It contains **no SQL** — only repository calls and graph invocation. Failures to
locate the requested job or profile surface as domain exceptions
(:class:`JobNotFoundError` / :class:`ProfileNotFoundError`); the API layer is
responsible for translating those into HTTP 404s, keeping this service free of
any web-framework coupling.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import compiled_graph
from app.core.logging import get_logger
from app.repositories.job_repository import JobRepository
from app.repositories.profile_repository import ProfileRepository
from app.utils.formatters import format_profile_to_markdown

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Domain exceptions                                                            #
# --------------------------------------------------------------------------- #
class PipelineError(Exception):
    """Base class for run_pipeline preconditions that cannot be satisfied."""


class JobNotFoundError(PipelineError):
    """No job posting exists for the requested ``job_id``."""


class ProfileNotFoundError(PipelineError):
    """No master profile exists for the requested ``profile_id``."""


def _build_job_text(job_title: str, company_name: str, description: str) -> str:
    """Collapse a posting's salient fields into a single prompt-ready block."""
    return f"# {job_title}\n**Company:** {company_name}\n\n{description}"


async def run_pipeline(
    job_id: uuid.UUID,
    profile_id: uuid.UUID,
    session: AsyncSession,
) -> dict[str, Any]:
    """Run the full match → draft → review pipeline for one job/profile pair.

    Orchestrates only: it resolves both aggregates through their repositories,
    formats them into the graph's text inputs, and invokes the compiled graph.
    No SQL is issued here directly.

    Args:
        job_id: Identifier of the target job posting.
        profile_id: Identifier of the candidate's master profile.
        session: Active async unit-of-work, shared by both repositories.

    Returns:
        The graph's final state as a plain ``dict`` (match score, drafts,
        review comments, etc.).

    Raises:
        JobNotFoundError: If ``job_id`` resolves to no posting.
        ProfileNotFoundError: If ``profile_id`` resolves to no profile.
    """
    job_repo = JobRepository(session)
    profile_repo = ProfileRepository(session)

    job = await job_repo.get_by_id(job_id)
    if job is None:
        raise JobNotFoundError(f"job posting {job_id} not found")

    profile = await profile_repo.get_full_profile(profile_id)
    if profile is None:
        raise ProfileNotFoundError(f"master profile {profile_id} not found")

    job_text = _build_job_text(job.job_title, job.company_name, job.description)
    profile_text = format_profile_to_markdown(profile)

    initial_state: dict[str, Any] = {
        "job_text": job_text,
        "profile_text": profile_text,
    }

    logger.info(
        "pipeline_started",
        extra={"job_id": str(job_id), "profile_id": str(profile_id)},
    )
    result = await compiled_graph.ainvoke(initial_state)
    logger.info(
        "pipeline_finished",
        extra={
            "job_id": str(job_id),
            "profile_id": str(profile_id),
            "match_score": result.get("match_score"),
        },
    )
    return result
