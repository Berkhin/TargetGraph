"""``EmailVerificationService`` — the orchestrator.

Pipeline (per ``Email_Verification_Spec.md``):

1. **Permutation** — generate candidate addresses from the name + domain.
2. **MX Resolution** — async DNS lookup; highest-priority host is used.
3. **Catch-All Check** — probe a random, guaranteed-nonexistent mailbox. A 2xx
   acceptance means the domain accepts everything → ``CATCH_ALL``; per-address
   verification is abandoned and flagged for manual handling.
4. **SMTP Ping** — probe candidates sequentially until the first 2xx acceptance.

The service is pure business logic: it takes a Pydantic request and returns a
Pydantic result. It never raises for *business* outcomes (no MX, catch-all, not
found) — those are statuses. It degrades gracefully: a dead proxy or DNS fault
yields ``PROXY_ERROR`` / ``DNS_ERROR`` rather than crashing the caller's task.
"""

from __future__ import annotations

import time
import uuid

from app.core.config import (
    EmailVerificationSettings,
    get_email_verification_settings,
)
from app.core.logging import get_logger
from app.services.email_verification.dns_resolver import resolve_mx_hosts
from app.services.email_verification.exceptions import (
    DnsResolutionError,
    ProxyConnectionError,
)
from app.services.email_verification.models import (
    EmailVerificationRequest,
    EmailVerificationResult,
    SmtpProbeResult,
    VerificationStatus,
)
from app.services.email_verification.permutations import generate_candidates
from app.services.email_verification.smtp_prober import SmtpProber

logger = get_logger(__name__)


class EmailVerificationService:
    """Discovers and verifies a recruiter's email address.

    Args:
        settings: Engine configuration. Defaults to the cached, env-derived
            settings; inject a custom instance in tests.
        prober: SMTP prober. Defaults to one built from ``settings``; inject a
            fake in tests to avoid real network traffic.
    """

    def __init__(
        self,
        settings: EmailVerificationSettings | None = None,
        prober: SmtpProber | None = None,
    ) -> None:
        self._settings = settings or get_email_verification_settings()
        self._prober = prober or SmtpProber(self._settings)

    async def verify(
        self, request: EmailVerificationRequest
    ) -> EmailVerificationResult:
        """Run the full discovery + verification pipeline for one person."""
        started = time.monotonic()
        log_ctx = {"domain": request.domain}
        logger.info("verification_started", extra=log_ctx)

        candidates = generate_candidates(
            request.first_name,
            request.last_name,
            request.domain,
            limit=self._settings.max_candidates,
        )
        if not candidates:
            return self._finish(
                request.domain,
                VerificationStatus.INCONCLUSIVE,
                started,
                detail="name produced no valid email candidates",
            )

        # --- Step 2: MX resolution ------------------------------------------
        try:
            mx_hosts = await resolve_mx_hosts(
                request.domain,
                timeout=self._settings.dns_timeout_seconds,
                lifetime=self._settings.dns_lifetime_seconds,
            )
        except DnsResolutionError as exc:
            logger.warning("verification_dns_error", extra={**log_ctx, "error": str(exc)})
            return self._finish(
                request.domain,
                VerificationStatus.DNS_ERROR,
                started,
                candidates_generated=len(candidates),
                detail=str(exc),
            )

        if not mx_hosts:
            return self._finish(
                request.domain,
                VerificationStatus.NO_MX_RECORDS,
                started,
                candidates_generated=len(candidates),
                detail="domain publishes no MX records",
            )

        mx_host = mx_hosts[0]
        log_ctx["mx_host"] = mx_host

        # --- Step 3: Catch-all guard ----------------------------------------
        try:
            catch_all_probe = await self._probe_catch_all(request.domain, mx_host)
        except ProxyConnectionError as exc:
            logger.error("verification_proxy_error", extra={**log_ctx, "error": str(exc)})
            return self._finish(
                request.domain,
                VerificationStatus.PROXY_ERROR,
                started,
                mx_host=mx_host,
                candidates_generated=len(candidates),
                detail=str(exc),
            )

        if catch_all_probe.deliverable:
            logger.info("verification_catch_all", extra=log_ctx)
            return self._finish(
                request.domain,
                VerificationStatus.CATCH_ALL,
                started,
                mx_host=mx_host,
                candidates_generated=len(candidates),
                probes=(catch_all_probe,),
                detail="domain is catch-all; address-level proof impossible",
            )

        # --- Step 4: SMTP ping until first acceptance -----------------------
        probes: list[SmtpProbeResult] = []
        try:
            for candidate in candidates:
                probe = await self._prober.probe(candidate.email, mx_host)
                probes.append(probe)
                if probe.deliverable:
                    return self._finish(
                        request.domain,
                        VerificationStatus.VERIFIED,
                        started,
                        verified_email=candidate.email,
                        mx_host=mx_host,
                        candidates_generated=len(candidates),
                        candidates_probed=len(probes),
                        probes=tuple(probes),
                        detail=f"verified via pattern '{candidate.pattern}'",
                    )
        except ProxyConnectionError as exc:
            # Proxy died mid-run: report what we have, but as a proxy fault.
            logger.error("verification_proxy_error", extra={**log_ctx, "error": str(exc)})
            return self._finish(
                request.domain,
                VerificationStatus.PROXY_ERROR,
                started,
                mx_host=mx_host,
                candidates_generated=len(candidates),
                candidates_probed=len(probes),
                probes=tuple(probes),
                detail=str(exc),
            )

        # No acceptance. Distinguish "definitively rejected everywhere" from
        # "inconclusive" (transient 4xx / timeouts) for graceful degradation.
        any_hard_reject = any(self._prober.is_hard_reject(p) for p in probes)
        status = (
            VerificationStatus.NOT_FOUND
            if any_hard_reject
            else VerificationStatus.INCONCLUSIVE
        )
        return self._finish(
            request.domain,
            status,
            started,
            mx_host=mx_host,
            candidates_generated=len(candidates),
            candidates_probed=len(probes),
            probes=tuple(probes),
            detail="no candidate was accepted by the MX server",
        )

    async def _probe_catch_all(self, domain: str, mx_host: str) -> SmtpProbeResult:
        """Probe a random local-part that cannot legitimately exist."""
        sentinel = f"{uuid.uuid4().hex}@{domain}"
        return await self._prober.probe(sentinel, mx_host)

    def _finish(
        self,
        domain: str,
        status: VerificationStatus,
        started: float,
        *,
        verified_email: str | None = None,
        mx_host: str | None = None,
        candidates_generated: int = 0,
        candidates_probed: int = 0,
        probes: tuple[SmtpProbeResult, ...] = (),
        detail: str = "",
    ) -> EmailVerificationResult:
        """Assemble the final result and emit a closing log line."""
        elapsed_ms = int((time.monotonic() - started) * 1000)
        result = EmailVerificationResult(
            domain=domain,
            status=status,
            verified_email=verified_email,
            mx_host=mx_host,
            candidates_generated=candidates_generated,
            candidates_probed=candidates_probed,
            probes=probes,
            elapsed_ms=elapsed_ms,
            detail=detail,
        )
        logger.info(
            "verification_finished",
            extra={
                "domain": domain,
                "status": status.value,
                "verified_email": verified_email,
                "elapsed_ms": elapsed_ms,
            },
        )
        return result
