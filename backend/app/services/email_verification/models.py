"""Pydantic models and enums — the strict I/O contract of the engine.

The service accepts an :class:`EmailVerificationRequest` and returns an
:class:`EmailVerificationResult`. Nothing here touches the database; these are
plain value objects so the component can be reused from a TaskIQ worker, a
FastAPI route, or a unit test interchangeably.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# A pragmatic domain matcher: labels of letters/digits/hyphen, dot-separated,
# with a final alphabetic TLD. Good enough to reject obviously bad input before
# we spend network budget on it.
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)(?:[A-Za-z0-9-]{1,63}(?<!-)\.)+[A-Za-z]{2,63}$"
)


class VerificationStatus(str, Enum):
    """Terminal status of a verification run.

    String-valued so it serialises cleanly to JSON / the WebSocket contract.
    """

    VERIFIED = "VERIFIED"
    """A deliverable address was confirmed via a 250 response."""

    NOT_FOUND = "NOT_FOUND"
    """MX exists, domain is not catch-all, but no candidate was accepted."""

    CATCH_ALL = "CATCH_ALL"
    """Domain accepts mail for any local-part; per-address proof is impossible."""

    NO_MX_RECORDS = "NO_MX_RECORDS"
    """The domain publishes no MX records — it cannot receive email here."""

    INCONCLUSIVE = "INCONCLUSIVE"
    """Graceful degradation: probing could not yield a definitive answer
    (e.g. greylisting, all candidates returned transient 4xx codes)."""

    PROXY_ERROR = "PROXY_ERROR"
    """The SOCKS5 proxy was unreachable — verification could not run safely."""

    DNS_ERROR = "DNS_ERROR"
    """MX resolution failed for a transport reason (timeout / SERVFAIL)."""


class EmailVerificationRequest(BaseModel):
    """Input: a person and the company domain to probe."""

    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    first_name: str = Field(min_length=1, max_length=128, examples=["Alex"])
    last_name: str = Field(min_length=1, max_length=128, examples=["Mercer"])
    domain: str = Field(min_length=3, max_length=253, examples=["company.com"])

    @field_validator("domain")
    @classmethod
    def _normalise_domain(cls, value: str) -> str:
        candidate = value.strip().lower().rstrip(".")
        # Tolerate a pasted URL or an email by extracting the host part.
        if "@" in candidate:
            candidate = candidate.rsplit("@", 1)[-1]
        candidate = candidate.removeprefix("http://").removeprefix("https://")
        candidate = candidate.split("/", 1)[0]
        if not _DOMAIN_RE.match(candidate):
            raise ValueError(f"invalid domain: {value!r}")
        return candidate


class EmailCandidate(BaseModel):
    """A generated address together with the pattern that produced it."""

    model_config = ConfigDict(frozen=True)

    email: str
    pattern: str = Field(description="Human-readable pattern id, e.g. 'first.last'.")


class SmtpProbeResult(BaseModel):
    """Outcome of a single SMTP RCPT TO probe."""

    model_config = ConfigDict(frozen=True)

    email: str
    deliverable: bool = Field(
        description="True only on a definitive 2xx acceptance of the recipient."
    )
    smtp_code: int | None = Field(
        default=None, description="Last SMTP status code observed, if any."
    )
    smtp_message: str | None = Field(
        default=None, description="Server reply text (trimmed)."
    )
    error: str | None = Field(
        default=None, description="Transport-level error, if the probe failed."
    )


class EmailVerificationResult(BaseModel):
    """Output: the full, strictly-typed verdict of a verification run."""

    model_config = ConfigDict(frozen=True)

    domain: str
    status: VerificationStatus
    verified_email: str | None = Field(
        default=None, description="The confirmed address when status==VERIFIED."
    )
    mx_host: str | None = Field(
        default=None, description="MX host (highest priority) that was probed."
    )
    candidates_generated: int = 0
    candidates_probed: int = 0
    probes: tuple[SmtpProbeResult, ...] = Field(default_factory=tuple)
    elapsed_ms: int = 0
    detail: str = Field(
        default="", description="Human-readable summary for logs / UI events."
    )
