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
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.orchestrator import compiled_graph
from app.core.logging import get_logger
from app.db.database import AsyncSessionLocal
from app.models.enums import JobStatus
from app.repositories.job_repository import JobRepository
from app.repositories.profile_repository import ProfileRepository
from app.utils.formatters import format_profile_to_markdown

logger = get_logger(__name__)

# Default minimum score to mark a posting MATCHED rather than REJECTED_BY_AI.
# Kept in sync with the REST ``/match`` endpoint and :func:`run_pipeline`.
_DEFAULT_SCORE_THRESHOLD = 70

# Graph-node names whose completion we forward to the websocket client.
# ``astream_events`` emits an ``on_chain_end`` for every nested runnable (LLM
# calls, structured-output chains, …); filtering on these names narrows the
# stream down to the four pipeline-node boundaries we actually want to report.
_PIPELINE_NODES = frozenset(
    {"extract_requirements", "match_profile", "draft_documents", "reviewer"}
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


def _build_job_text(job_title: str, company_name: str, description: str) -> str:
    """Collapse a posting's salient fields into a single prompt-ready block."""
    return f"# {job_title}\n**Company:** {company_name}\n\n{description}"


async def run_pipeline(
    job_id: uuid.UUID,
    profile_id: uuid.UUID,
    session: AsyncSession,
    save_results: bool = False,
    score_threshold: int = 70,
) -> dict[str, Any]:
    """Run the full match → draft → review pipeline for one job/profile pair.

    Orchestrates: resolves both aggregates through repositories, formats them
    into graph text inputs, invokes the compiled graph, and optionally saves
    results back to the job posting.

    Args:
        job_id: Identifier of the target job posting.
        profile_id: Identifier of the candidate's master profile.
        session: Active async unit-of-work, shared by both repositories.
        save_results: If ``True``, persist match results to the database.
        score_threshold: Minimum match score to mark as MATCHED (vs REJECTED_BY_AI).

    Returns:
        The graph's final state as a plain ``dict`` (match score, drafts,
        review comments, etc.).

    Raises:
        JobNotFoundError: If ``job_id`` resolves to no posting.
        ProfileNotFoundError: If ``profile_id`` resolves to no profile.
        PipelineExecutionError: If graph invocation fails.
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

    if save_results:
        match_score = result.get("match_score", 0)
        cover_letter = result.get("cover_letter_draft", "")
        status = (
            JobStatus.MATCHED
            if match_score >= score_threshold
            else JobStatus.REJECTED_BY_AI
        )
        await job_repo.save_match_results(
            job_id, match_score, cover_letter, status
        )
        logger.info(
            "pipeline_results_saved",
            extra={
                "job_id": str(job_id),
                "match_score": match_score,
                "status": status.value,
            },
        )

    return result


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
    surfaces lazily — and with a server-dependent exception type — on a later
    ``send``. Running this concurrently with the graph lets the main loop notice a
    gone client at the next node boundary, stop wasting LLM calls, and skip
    persisting a result nobody is waiting for.
    """
    try:
        while True:
            await websocket.receive()
    except WebSocketDisconnect:
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

    initial_state: dict[str, Any] = {
        "job_text": _build_job_text(job.job_title, job.company_name, job.description),
        "profile_text": format_profile_to_markdown(profile),
    }
    await _safe_send(websocket, {"step": "init", "message": "Данные загружены"})
    logger.info(
        "pipeline_stream_started",
        extra={"job_id": str(job_id), "profile_id": str(profile_id)},
    )
    started = time.perf_counter()

    # --- 2) Drive the graph holding NO db connection ------------------------
    # Merge every node's partial output into ``final_state`` as it lands. Last
    # write wins, which is exactly right for ``draft_documents`` (it may re-run in
    # the revision loop, leaving the latest cover letter). A watcher task lets us
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
        with suppress(asyncio.CancelledError):
            await watcher

    # --- 3) Short write session: its own atomic unit of work ----------------
    match_score = final_state.get("match_score") or 0
    cover_letter = final_state.get("cover_letter_draft") or ""
    result_status = (
        JobStatus.MATCHED
        if match_score >= score_threshold
        else JobStatus.REJECTED_BY_AI
    )
    try:
        async with session_factory() as session:
            await JobRepository(session).save_match_results(
                job_id, match_score, cover_letter, result_status
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
            "match_score": match_score,
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
            "score": match_score,
            "reason": final_state.get("match_reasoning", ""),
            "cover_letter_draft": cover_letter or None,
        },
    )
    await _safe_close(websocket)
