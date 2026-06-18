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

import asyncio
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.orchestrator import compiled_graph
from app.core.logging import get_logger
from app.db.database import AsyncSessionLocal
from app.models.enums import JobStatus
from app.models.schemas.job import JobRead
from app.models.schemas.profile import ProfileRead
from app.repositories.job_repository import JobRepository
from app.repositories.profile_repository import ProfileRepository
from app.utils.formatters import format_profile_to_markdown

logger = get_logger(__name__)

# Default minimum score to mark a posting MATCHED rather than REJECTED_BY_AI, and
# the cutoff the graph's drafting gate uses. The single source of truth for the
# match threshold — referenced by :func:`run_pipeline`, the streaming sibling, and
# the REST ``/match`` endpoint. Equal to the prompt's hard-skill cap (50): a job
# missing a critical hard skill is capped at 50 by the rubric, so it can still
# just reach the bar and get a CV/cover letter drafted.
_DEFAULT_SCORE_THRESHOLD = 50

# Graph-node names whose completion we forward to the websocket client.
# ``astream_events`` emits an ``on_chain_end`` for every nested runnable (LLM
# calls, structured-output chains, …); filtering on these names narrows the
# stream down to the four pipeline-node boundaries we actually want to report.
_PIPELINE_NODES = frozenset(
    {
        "extract_requirements",
        "match_profile",
        "find_recruiter_contact",
        "generate_cover_letter",
        "generate_tailored_cv",
        "reviewer",
    }
)


# --------------------------------------------------------------------------- #
# Domain exceptions                                                            #
# --------------------------------------------------------------------------- #
class PipelineError(Exception):
    """Base class for run_pipeline preconditions that cannot be satisfied."""


class JobNotFoundError(PipelineError):
    """No job posting exists for the requested ``job_id``."""


class ProfileNotFoundError(PipelineError):
    """No master profile exists for the requested ``profile_id``."""


class PipelineExecutionError(PipelineError):
    """Graph invocation failed (LLM error, node failure, timeout, etc.)."""

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


class PipelineDegradedError(PipelineError):
    """The pipeline ran but produced no persistable verdict (model quota).

    Either the job could not be scored (``analysis_failed``) or it matched but the
    cover letter could not be generated. Nothing is persisted, so the job stays
    ``NEW`` and retryable; the API layer maps this to a 503.
    """


# --------------------------------------------------------------------------- #
# Match verdict                                                                #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MatchOutcome:
    """The persistable verdict distilled from the graph's final state.

    Single source of truth for the save/skip decision shared by the REST
    endpoint and the streaming sibling: the MATCHED/REJECTED threshold rule and
    the "never persist a false verdict" guard live here, not at each call site.
    ``analysis_failed`` (the job could not be scored) and ``generation_unavailable``
    (matched, but the letter failed) are kept distinct so the streaming path can
    report a different message for each.
    """

    match_score: int
    match_reasoning: str
    cover_letter: str
    tailored_cv: str | None
    recruiter_name: str | None
    recruiter_email: str | None
    analysis_failed: bool
    drafting_failed: bool
    score_threshold: int

    @property
    def is_match(self) -> bool:
        return self.match_score >= self.score_threshold

    @property
    def status(self) -> JobStatus:
        return JobStatus.MATCHED if self.is_match else JobStatus.REJECTED_BY_AI

    @property
    def generation_unavailable(self) -> bool:
        """Matched on score, but no usable cover letter was produced."""
        return self.is_match and (self.drafting_failed or not self.cover_letter.strip())

    @property
    def can_persist(self) -> bool:
        """False when saving would record a false REJECTED or a broken MATCHED."""
        return not (self.analysis_failed or self.generation_unavailable)


def parse_match_outcome(state: dict[str, Any], score_threshold: int) -> MatchOutcome:
    """Distil a graph final-state dict into a :class:`MatchOutcome`.

    Coerces the score with ``or 0`` so an explicit ``None`` from a degraded node
    never reaches the threshold comparison (which would raise on ``None >= int``).
    """
    return MatchOutcome(
        match_score=state.get("match_score") or 0,
        match_reasoning=state.get("match_reasoning", ""),
        cover_letter=state.get("cover_letter_draft") or "",
        tailored_cv=state.get("tailored_cv"),
        recruiter_name=state.get("recruiter_name"),
        recruiter_email=state.get("recruiter_email"),
        analysis_failed=bool(state.get("analysis_failed")),
        drafting_failed=bool(state.get("drafting_failed")),
        score_threshold=score_threshold,
    )


def _build_job_text(job_title: str, company_name: str, description: str) -> str:
    """Collapse a posting's salient fields into a single prompt-ready block."""
    return f"# {job_title}\n**Company:** {company_name}\n\n{description}"


def build_initial_state(
    job: JobRead, profile: ProfileRead, score_threshold: int
) -> dict[str, Any]:
    """Render a job + profile into the graph's initial state dict.

    Shared by :func:`run_pipeline` and :func:`run_pipeline_stream` so both feed
    the graph identical inputs: the job/profile text, the employer identity the
    recruiter-lookup node needs, and the drafting threshold.
    """
    return {
        "job_text": _build_job_text(job.job_title, job.company_name, job.description),
        "profile_text": format_profile_to_markdown(profile),
        # Employer identity for the recruiter-lookup node (Hunter.io). Lookup
        # precedence is company_website -> employer domain from source_url ->
        # company_name (see find_recruiter_contact).
        "company_name": job.company_name,
        "source_url": job.source_url,
        "company_website": job.company_website,
        # Gate drafting on the same threshold used for MATCHED/REJECTED, so a
        # sub-threshold job is rejected without spending drafting LLM calls.
        "score_threshold": score_threshold,
    }


async def run_pipeline(
    job_id: uuid.UUID,
    profile_id: uuid.UUID,
    session: AsyncSession,
    score_threshold: int = _DEFAULT_SCORE_THRESHOLD,
) -> dict[str, Any]:
    """Run the full match → draft → review pipeline for one job/profile pair.

    Pure orchestration, no persistence: resolves both aggregates through
    repositories, formats them into graph text inputs, invokes the compiled
    graph, and returns the final state. Persisting the verdict is the caller's
    job (see :func:`match_and_save`), which keeps this function reusable for
    read-only/preview runs.

    Args:
        job_id: Identifier of the target job posting.
        profile_id: Identifier of the candidate's master profile.
        session: Active async unit-of-work, shared by both repositories.
        score_threshold: Drafting gate — sub-threshold jobs skip the draft nodes.

    Returns:
        The graph's final state as a plain ``dict`` (match score, drafts,
        review comments, etc.).

    Raises:
        JobNotFoundError: If ``job_id`` resolves to no posting.
        ProfileNotFoundError: If ``profile_id`` resolves to no profile.
        PipelineExecutionError: If graph invocation fails.
    """
    job = await JobRepository(session).get_by_id(job_id)
    if job is None:
        raise JobNotFoundError(f"job posting {job_id} not found")

    profile = await ProfileRepository(session).get_full_profile(profile_id)
    if profile is None:
        raise ProfileNotFoundError(f"master profile {profile_id} not found")

    initial_state = build_initial_state(job, profile, score_threshold)

    logger.info(
        "pipeline_started",
        extra={"job_id": str(job_id), "profile_id": str(profile_id)},
    )
    try:
        result = await compiled_graph.ainvoke(initial_state)
    except Exception as e:
        logger.error(
            "pipeline_execution_failed",
            extra={
                "job_id": str(job_id),
                "profile_id": str(profile_id),
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        raise PipelineExecutionError(
            f"AI pipeline failed for job {job_id}: {type(e).__name__}",
            cause=e,
        ) from e

    logger.info(
        "pipeline_finished",
        extra={
            "job_id": str(job_id),
            "profile_id": str(profile_id),
            "match_score": result.get("match_score"),
        },
    )
    return result


async def match_and_save(
    job_id: uuid.UUID,
    profile_id: uuid.UUID,
    session: AsyncSession,
    score_threshold: int = _DEFAULT_SCORE_THRESHOLD,
) -> JobRead:
    """Run the pipeline for a job/profile, persist the verdict, return the job.

    The single service entry point behind the REST ``/match`` endpoint: it keeps
    the threshold/persist decision out of the router, which only maps the domain
    exceptions to HTTP status codes.

    Raises:
        JobNotFoundError / ProfileNotFoundError: unknown id (from run_pipeline).
        PipelineExecutionError: graph invocation failed (from run_pipeline).
        PipelineDegradedError: nothing persistable was produced (model quota) —
            the job is left ``NEW`` and retryable.
    """
    result = await run_pipeline(job_id, profile_id, session, score_threshold)
    outcome = parse_match_outcome(result, score_threshold)

    if not outcome.can_persist:
        logger.warning(
            "match_results_unavailable",
            extra={
                "job_id": str(job_id),
                "match_score": outcome.match_score,
                "analysis_failed": outcome.analysis_failed,
                "drafting_failed": outcome.drafting_failed,
            },
        )
        raise PipelineDegradedError(
            "AI evaluation/generation is unavailable (model quota)."
        )

    saved = await JobRepository(session).save_match_results(
        job_id,
        outcome.match_score,
        outcome.cover_letter,
        outcome.status,
        outcome.tailored_cv,
        recruiter_name=outcome.recruiter_name,
        recruiter_email=outcome.recruiter_email,
    )
    if saved is None:
        # The posting existed when run_pipeline loaded it; vanishing mid-request
        # is an integrity failure, not a routine 404.
        raise PipelineExecutionError(
            f"job posting {job_id} disappeared after matching"
        )

    logger.info(
        "pipeline_results_saved",
        extra={
            "job_id": str(job_id),
            "match_score": outcome.match_score,
            "status": outcome.status.value,
        },
    )
    return saved


async def _safe_send(websocket: WebSocket, payload: dict[str, Any]) -> None:
    """Send a frame, swallowing *any* error — the socket may already be gone.

    On a dead connection ``send_json`` can raise more than
    :class:`WebSocketDisconnect`: depending on the ASGI server it may surface as
    ``RuntimeError``, a ``websockets`` ``ConnectionClosed*``, or similar. Cleanup
    and best-effort notifications must never let one of those escape and leave the
    socket half-open, so this catches broadly by design.
    """
    try:
        await websocket.send_json(payload)
    except Exception:  # noqa: BLE001 — best-effort; a broken socket is not an error here
        pass


async def _safe_close(websocket: WebSocket) -> None:
    """Close the socket, swallowing any error (it may already be closed)."""
    try:
        await websocket.close()
    except Exception:  # noqa: BLE001 — see _safe_send
        pass


async def _safe_error(websocket: WebSocket, message: str) -> None:
    """Best-effort error frame followed by a close."""
    await _safe_send(websocket, {"step": "error", "message": message})
    await _safe_close(websocket)


async def _watch_disconnect(websocket: WebSocket) -> None:
    """Block until the client disconnects.

    ``WebSocket.receive()`` is the *only* call Starlette routes the ASGI
    ``websocket.disconnect`` message through. A handler that merely streams
    (``send`` only, never ``receive``) cannot observe a closed tab: the disconnect
    surfaces lazily on a later ``receive``. Running this concurrently with the
    graph lets the main loop notice a gone client at the next node boundary, stop
    wasting LLM calls, and skip persisting a result nobody is waiting for.

    Crucially, the low-level ``receive()`` does NOT raise on disconnect — it
    *returns* the ``{"type": "websocket.disconnect"}`` message and flips the
    socket to DISCONNECTED; a *second* ``receive()`` then raises ``RuntimeError``.
    So the disconnect must be detected on the message itself and the loop must
    stop there, never spinning into that ``RuntimeError``. Any other receive
    error after the peer is gone is likewise treated as "client gone" rather than
    leaked out, so the watcher task always finishes cleanly.
    """
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001 — a broken receive == client is gone
        return


async def run_pipeline_stream(
    job_id: uuid.UUID,
    profile_id: uuid.UUID,
    websocket: WebSocket,
    score_threshold: int = _DEFAULT_SCORE_THRESHOLD,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
) -> None:
    """Stream the match → draft → review pipeline to a websocket, node by node.

    The streaming sibling of :func:`run_pipeline`. Instead of awaiting the whole
    graph and returning the final state, it drives the graph through
    ``astream_events`` and forwards each node boundary to the client as it
    happens, so the user watches progress instead of waiting ~30s for a single
    verdict. The ``match_profile`` node is surfaced specially: its score and
    reasoning are pushed the moment that node finishes, so a low-score rejection
    reaches the user *with its reason* before anything else.

    **Connection discipline.** The LangGraph pipeline is DB-agnostic, so no
    database connection is held while it runs (which can take tens of seconds of
    LLM time). Inputs are read in a short session that is released before the
    graph starts, and results are saved in a second short session afterwards —
    mirroring :func:`~app.tasks.sourcing_task.run_sourcing_job`. This keeps a
    handful of abandoned streams from pinning the whole connection pool.

    **Disconnect handling.** A concurrent :func:`_watch_disconnect` task makes a
    closed tab observable mid-run (``send``-only handlers cannot detect it
    reliably). On disconnect the graph loop stops and nothing is persisted; the
    server never crashes. The caller (the websocket route) owns
    ``websocket.accept()``; this function owns every subsequent frame and the
    close, and never propagates :class:`WebSocketDisconnect`.

    Args:
        job_id: Identifier of the target job posting.
        profile_id: Identifier of the candidate's master profile.
        websocket: The already-accepted client connection.
        score_threshold: Minimum match score to mark MATCHED (vs REJECTED_BY_AI).
        session_factory: Async session factory. Injectable so tests can pass a
            SQLite-backed factory (see ``run_sourcing_job``).
    """
    # --- 1) Short read session: load inputs, then release the connection ----
    async with session_factory() as session:
        job = await JobRepository(session).get_by_id(job_id)
        profile = await ProfileRepository(session).get_full_profile(profile_id)
    # Connection is back in the pool before the (potentially long) graph run.

    if job is None:
        await _safe_error(websocket, f"job posting {job_id} not found")
        return
    if profile is None:
        await _safe_error(websocket, f"profile {profile_id} not found")
        return

    initial_state = build_initial_state(job, profile, score_threshold)
    await _safe_send(websocket, {"step": "init", "message": "Данные загружены"})
    logger.info(
        "pipeline_stream_started",
        extra={"job_id": str(job_id), "profile_id": str(profile_id)},
    )
    started = time.perf_counter()

    # --- 2) Drive the graph holding NO db connection ------------------------
    # Merge every node's partial output into ``final_state`` as it lands. Last
    # write wins, which is exactly right for ``generate_cover_letter`` (it may re-run
    # in the revision loop, leaving the latest cover letter). A watcher task lets us
    # bail the moment the client goes away.
    watcher = asyncio.create_task(_watch_disconnect(websocket))
    final_state: dict[str, Any] = dict(initial_state)
    try:
        async for event in compiled_graph.astream_events(initial_state, version="v2"):
            if watcher.done():
                # Client vanished mid-run: stop burning LLM calls and skip the save.
                raise WebSocketDisconnect()
            if event["event"] != "on_chain_end":
                continue
            node = event.get("name")
            if node not in _PIPELINE_NODES:
                continue
            output = event["data"].get("output")
            if not isinstance(output, dict):
                continue
            final_state.update(output)

            if node == "match_profile":
                # Push the verdict and its reasoning immediately — this is the
                # message the UI uses to explain an early rejection.
                await websocket.send_json(
                    {
                        "step": "match_profile",
                        "score": output.get("match_score"),
                        "reason": output.get("match_reasoning"),
                    }
                )
            elif node == "find_recruiter_contact":
                # Surface what the Hunter.io lookup resolved (or that nothing was
                # found, hence the generic 'Dear Hiring Team' greeting).
                await websocket.send_json(
                    {
                        "step": "find_recruiter_contact",
                        "recruiter_name": output.get("recruiter_name"),
                        "recruiter_email": output.get("recruiter_email"),
                    }
                )
            else:
                await websocket.send_json(
                    {"step": node, "message": f"Шаг '{node}' завершён"}
                )
    except WebSocketDisconnect:
        logger.info(
            "pipeline_stream_client_disconnected",
            extra={
                "job_id": str(job_id),
                "profile_id": str(profile_id),
                "elapsed_s": round(time.perf_counter() - started, 3),
            },
        )
        return  # nothing persisted; no db connection to roll back
    except Exception:  # noqa: BLE001 — report, but never crash the server
        logger.exception(
            "pipeline_stream_failed",
            extra={"job_id": str(job_id), "profile_id": str(profile_id)},
        )
        await _safe_error(websocket, "AI pipeline execution failed.")
        return
    finally:
        watcher.cancel()
        # Awaiting the watcher must never let anything escape run_pipeline_stream
        # (and from there the un-guarded ASGI endpoint). Two cases to swallow:
        #   * the healthy path cancels the watcher -> CancelledError (a
        #     BaseException, so NOT covered by ``Exception``);
        #   * any server-specific error from a broken receive.
        with suppress(asyncio.CancelledError, Exception):
            await watcher

    # --- 3) Short write session: its own atomic unit of work ----------------
    outcome = parse_match_outcome(final_state, score_threshold)

    # The job could not be evaluated (LLM/quota error during extract/match). Don't
    # persist a false REJECTED — leave it NEW and retryable, and say why.
    if outcome.analysis_failed:
        logger.warning(
            "pipeline_stream_analysis_unavailable",
            extra={"job_id": str(job_id)},
        )
        await _safe_error(
            websocket,
            "Не удалось оценить вакансию (лимит/квота модели). "
            "Вакансия осталась в списке — попробуйте позже.",
        )
        return

    # Matched on score, but the cover letter could not be generated (e.g. the
    # generation model hit its quota). Don't persist a broken MATCHED — leave the
    # job NEW so it can be retried once quota is back, and tell the user why.
    if outcome.generation_unavailable:
        logger.warning(
            "pipeline_stream_generation_unavailable",
            extra={"job_id": str(job_id), "match_score": outcome.match_score},
        )
        await _safe_error(
            websocket,
            f"Совпадение {outcome.match_score}%, но генерация недоступна "
            "(лимит/квота модели). Вакансия осталась в списке — попробуйте позже.",
        )
        return

    result_status = outcome.status
    try:
        async with session_factory() as session:
            await JobRepository(session).save_match_results(
                job_id,
                outcome.match_score,
                outcome.cover_letter,
                result_status,
                outcome.tailored_cv,
                recruiter_name=outcome.recruiter_name,
                recruiter_email=outcome.recruiter_email,
            )
            await session.commit()
    except Exception:  # noqa: BLE001 — surface to the client, never crash the server
        logger.exception(
            "pipeline_stream_persist_failed",
            extra={"job_id": str(job_id), "profile_id": str(profile_id)},
        )
        await _safe_error(websocket, "Failed to persist match result.")
        return

    logger.info(
        "pipeline_stream_finished",
        extra={
            "job_id": str(job_id),
            "match_score": outcome.match_score,
            "status": result_status.value,
            "elapsed_s": round(time.perf_counter() - started, 3),
        },
    )

    # --- 4) Final frame + close --------------------------------------------
    # Repeat the reason on the closing frame so a rejection is never silent, even
    # for a client that missed the intermediate ``match_profile`` event.
    await _safe_send(
        websocket,
        {
            "step": "done",
            "status": result_status.value,
            "score": outcome.match_score,
            "reason": outcome.match_reasoning,
            "cover_letter_draft": outcome.cover_letter or None,
            "tailored_cv_draft": outcome.tailored_cv or None,
        },
    )
    await _safe_close(websocket)
