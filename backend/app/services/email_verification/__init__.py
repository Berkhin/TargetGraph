"""Email Discovery & Verification Engine.

A self-contained, DB-agnostic service that:

1. Permutes likely email addresses from a name + company domain.
2. Resolves the domain's MX records asynchronously (``dnspython``).
3. Detects Catch-All domains by probing a guaranteed-nonexistent mailbox.
4. SMTP-probes the candidates (HELO / MAIL FROM / RCPT TO / QUIT) until the
   first deliverable address is found.

Every SMTP connection is routed through a SOCKS5 proxy (``python-socks`` +
``aiosmtplib``). The public surface is intentionally small: construct a
:class:`EmailVerificationService` and ``await`` :meth:`verify`.
"""

from __future__ import annotations

from app.services.email_verification.models import (
    EmailCandidate,
    EmailVerificationRequest,
    EmailVerificationResult,
    SmtpProbeResult,
    VerificationStatus,
)
from app.services.email_verification.service import EmailVerificationService

__all__ = [
    "EmailCandidate",
    "EmailVerificationRequest",
    "EmailVerificationResult",
    "EmailVerificationService",
    "SmtpProbeResult",
    "VerificationStatus",
]
