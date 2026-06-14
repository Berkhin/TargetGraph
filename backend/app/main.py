"""FastAPI application entry point.

Minimal host for the email-verification engine. Other subsystems (jobs,
applications, webhooks, websockets) register their routers here as they land.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.api.v1 import email_verification
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Configure logging on start-up; uvicorn drives graceful shutdown."""
    configure_logging(logging.INFO)
    logger.info("application_startup")
    try:
        yield
    finally:
        logger.info("application_shutdown")


app = FastAPI(title="TargetGraph.io API", version="0.1.0", lifespan=lifespan)
app.include_router(email_verification.router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness probe for Docker / orchestrator health checks."""
    return {"status": "ok"}
