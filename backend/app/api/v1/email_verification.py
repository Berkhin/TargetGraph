"""FastAPI router exposing the email-verification engine.

This is a thin adapter: it depends on :class:`EmailVerificationService` and maps
its Pydantic result straight to JSON. The heavy lifting stays in the service so
it can equally be invoked from a TaskIQ background worker (the production path —
verification is slow and proxy-bound, so it should not block a request thread).
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends

from app.services.email_verification import (
    EmailVerificationRequest,
    EmailVerificationResult,
    EmailVerificationService,
)

router = APIRouter(prefix="/api/v1", tags=["email-verification"])


@lru_cache
def get_email_verification_service() -> EmailVerificationService:
    """Provide a shared service instance (stateless, safe to reuse)."""
    return EmailVerificationService()


@router.post("/contacts/verify-email", response_model=EmailVerificationResult)
async def verify_email(
    request: EmailVerificationRequest,
    service: EmailVerificationService = Depends(get_email_verification_service),
) -> EmailVerificationResult:
    """Discover and verify a recruiter's email from name + company domain.

    Always returns ``200`` with a strict result body; business outcomes (no MX,
    catch-all, not found, proxy/DNS degradation) are carried in ``status``.
    """
    return await service.verify(request)
