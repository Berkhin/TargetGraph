"""Hunter.io email-discovery integration — the cold-outreach layer's seam.

This module is the *only* place that talks to Hunter. Given a company domain (or
just a company name) it finds the email addresses of recruiters / hiring
managers there, so a later outreach stage can reach a real, named person rather
than a generic inbox.

Hunter's v2 ``domain-search`` works on the free plan and returns the email
*plus* the person's name, job title, and LinkedIn URL — exactly the fields we
need to reach a named recruiter rather than a generic mailbox.

Resilience over completeness: cold outreach is an optional enrichment step, so
*any* failure (network error, bad key, exhausted Hunter credits) is logged and
degraded to an empty list. One company we cannot enrich must never abort the
surrounding pipeline.
"""

from __future__ import annotations

from contextlib import AsyncExitStack

import httpx

from app.core.config import get_hunter_settings
from app.core.logging import get_logger
from app.models.schemas.hunter import HunterContact

logger = get_logger(__name__)

# Hunter's v2 domain-search endpoint: every email known for a domain, each with
# the person's name, position, and LinkedIn handle.
_HUNTER_DOMAIN_SEARCH_URL = "https://api.hunter.io/v2/domain-search"

# Hunter "department" value that captures recruiters / talent acquisition. The
# API accepts a comma-separated list, so callers can broaden it (e.g. add
# "executive" seniority) when hiring managers sit outside HR.
_DEFAULT_DEPARTMENT = "hr"

# domain-search is a single GET; a bounded timeout keeps a hung request from
# stalling the caller while still allowing for normal latency.
_REQUEST_TIMEOUT_SECONDS = 30.0


class HunterClient:
    """Async client for Hunter.io domain search.

    Pass a shared :class:`httpx.AsyncClient` to reuse a connection pool across
    calls; if omitted, one is created per request.
    """

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._settings = get_hunter_settings()

    async def search_hiring_managers(
        self,
        domain: str | None = None,
        *,
        company: str | None = None,
        department: str | None = _DEFAULT_DEPARTMENT,
        limit: int = 10,
    ) -> list[HunterContact]:
        """Find named recruiter / hiring-manager emails at a company.

        Identify the company by ``domain`` (preferred — unambiguous) or by
        ``company`` name (Hunter resolves it to a domain server-side). At least
        one must be given; if both are, Hunter gives the domain precedence. The
        company-name path matters here because the surrounding pipeline sources
        from LinkedIn, whose URLs never carry the employer's own domain.

        Args:
            domain: Target company domain (e.g. ``"acme.com"``).
            company: Company name (e.g. ``"Acme Inc"``), used when no domain is
                available.
            department: Hunter department filter (comma-separated). Defaults to
                ``"hr"`` to surface recruiters; pass ``None`` to search every
                department, or e.g. ``"hr,executive"`` to widen.
            limit: Max email records to request (Hunter free plan caps
                ``limit + offset`` at 10).

        Returns:
            Only contacts that are personal addresses *with a known first name*
            (see the strict filter below) — we must have a name to personalise
            outreach. Empty if nothing qualifies or the request fails (logged).
        """
        if not domain and not company:
            logger.error("hunter_search_no_identifier")
            return []

        # Hunter authenticates via the ``api_key`` query parameter and accepts
        # either ``domain`` or ``company`` to identify the employer.
        params: dict[str, object] = {
            "api_key": self._settings.hunter_api_key,
            "limit": limit,
        }
        if domain:
            params["domain"] = domain
        if company:
            params["company"] = company
        if department:
            params["department"] = department

        try:
            # Reuse the injected client if given, else create one scoped to this
            # call; either way the per-request timeout applies uniformly so a hung
            # request can never stall the caller.
            async with AsyncExitStack() as stack:
                client = self._client or await stack.enter_async_context(
                    httpx.AsyncClient()
                )
                response = await client.get(
                    _HUNTER_DOMAIN_SEARCH_URL,
                    params=params,
                    timeout=_REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                # Parse inside the context (and the try): a 200 with a non-JSON
                # body (HTML stub, truncated response) raises ValueError
                # (json.JSONDecodeError), which is NOT an httpx.HTTPError — without
                # catching it here it would escape the documented fail-soft
                # contract. Reading the body while the owned client is still open.
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.error(
                "hunter_search_failed",
                extra={
                    "domain": domain,
                    "company": company,
                    "error_type": type(exc).__name__,
                },
            )
            return []

        data = payload.get("data") or {}
        raw_emails = data.get("emails") or []
        contacts = [
            HunterContact(
                email=record.get("value"),
                first_name=record.get("first_name"),
                last_name=record.get("last_name"),
                position=record.get("position"),
                # domain-search names this field ``linkedin`` (email-finder uses
                # ``linkedin_url``); we normalise to linkedin_url on the DTO.
                linkedin_url=record.get("linkedin"),
                confidence=record.get("confidence"),
            )
            for record in raw_emails
            if self._is_personal_named(record)
        ]

        # Diagnostic: log exactly what Hunter returned and what survived the
        # personal+named filter, so an "always generic greeting" can be traced to
        # its cause (zero results vs. everything filtered out vs. wrong company).
        logger.info(
            "hunter_search_result",
            extra={
                "domain": domain,
                "company": company,
                # Hunter echoes the domain/org it actually resolved a name to.
                "resolved_domain": data.get("domain"),
                "resolved_organization": data.get("organization"),
                "raw_count": len(raw_emails),
                "kept_count": len(contacts),
                "records": [
                    {
                        "email": r.get("value"),
                        "type": r.get("type"),
                        "first_name": r.get("first_name"),
                        "last_name": r.get("last_name"),
                        "position": r.get("position"),
                        "confidence": r.get("confidence"),
                    }
                    for r in raw_emails[:25]
                ],
            },
        )
        return contacts

    @staticmethod
    def _is_personal_named(record: dict) -> bool:
        """Keep only addresses we can use for *personalised* outreach.

        Strict gate: drop generic role mailboxes (``careers@``, ``jobs@``,
        ``info@`` — Hunter tags these ``type == "generic"``) and any record
        without a real first name, since the cover-letter salutation depends on
        knowing who we are writing to.
        """
        first_name = (record.get("first_name") or "").strip()
        return record.get("type") == "personal" and bool(first_name)
