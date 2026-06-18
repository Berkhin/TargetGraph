"""FastAPI application entry point.

Minimal host for the email-verification engine. Other subsystems (jobs,
applications, webhooks, websockets) register their routers here as they land.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import email_verification, jobs, profiles
from app.core.config import get_cors_settings, get_sourcing_settings
from app.core.logging import configure_logging, get_logger
from app.tasks.sourcing_task import run_sourcing_job

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configure logging and the background sourcing scheduler on start-up.

    The scheduler runs the periodic Apify LinkedIn-Jobs sourcing task on an
    interval. ``get_sourcing_settings()`` is resolved here so a missing
    ``APIFY_TOKEN`` fails fast at start-up rather than on every (silently
    failing) scheduled run.
    """
    configure_logging(logging.INFO)
    logger.info("application_startup")

    sourcing_settings = get_sourcing_settings()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_sourcing_job,
        trigger="interval",
        hours=sourcing_settings.interval_hours,
        id="sourcing",
        max_instances=1,  # never overlap a long run with the next tick
        coalesce=True,  # collapse missed runs into a single catch-up
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "scheduler_started",
        extra={"interval_hours": sourcing_settings.interval_hours},
    )

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")
        logger.info("application_shutdown")


app = FastAPI(title="TargetGraph.io API", version="0.1.0", lifespan=lifespan)

_cors_settings = get_cors_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_settings.allow_origins,
    # Reserved for future cookie/session auth. Safe with the explicit origin
    # list above; must NOT be combined with a wildcard origin (browsers reject
    # `*` + credentials), so keep allow_origins explicit if this stays True.
    allow_credentials=True,
    # The API only exposes these verbs (plus preflight OPTIONS); narrower than
    # "*" to keep the surface tight.
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(profiles.router)
app.include_router(email_verification.router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness probe for Docker / orchestrator health checks."""
    return {"status": "ok"}
