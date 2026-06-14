"""Pipeline tests for EmailVerificationService.

No real network is touched: MX resolution is monkeypatched and the SMTP prober
is replaced with a deterministic fake. This isolates the orchestration logic
(catch-all guard, first-hit early exit, graceful degradation).
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from app.services.email_verification import (
    EmailVerificationRequest,
    EmailVerificationService,
    SmtpProbeResult,
    VerificationStatus,
)
from app.services.email_verification import service as service_module
from app.services.email_verification.exceptions import (
    DnsResolutionError,
    ProxyConnectionError,
)
from app.services.email_verification.smtp_prober import SmtpProber

_UUID_LOCAL = re.compile(r"^[0-9a-f]{32}@")


def _request() -> EmailVerificationRequest:
    return EmailVerificationRequest(
        first_name="Alex", last_name="Mercer", domain="company.com"
    )


class _FakeProber:
    """Returns whatever the injected responder dictates for each email."""

    def __init__(self, responder: Callable[[str], SmtpProbeResult]) -> None:
        self._responder = responder
        self.calls: list[str] = []

    async def probe(self, email: str, mx_host: str) -> SmtpProbeResult:
        self.calls.append(email)
        return self._responder(email)

    @staticmethod
    def is_hard_reject(result: SmtpProbeResult) -> bool:
        return SmtpProber.is_hard_reject(result)


def _accept(email: str) -> SmtpProbeResult:
    return SmtpProbeResult(email=email, deliverable=True, smtp_code=250, smtp_message="OK")


def _reject(email: str, code: int = 550) -> SmtpProbeResult:
    return SmtpProbeResult(email=email, deliverable=False, smtp_code=code, smtp_message="no such user")


@pytest.fixture(autouse=True)
def _mx_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: domain has one MX host."""
    async def fake_resolve(domain: str, **_: object) -> list[str]:
        return ["mx1.company.com"]

    monkeypatch.setattr(service_module, "resolve_mx_hosts", fake_resolve)


def _service(responder: Callable[[str], SmtpProbeResult]) -> tuple[EmailVerificationService, _FakeProber]:
    prober = _FakeProber(responder)
    return EmailVerificationService(prober=prober), prober  # type: ignore[arg-type]


async def test_verified_returns_first_accepted_address() -> None:
    # Catch-all sentinel is rejected; the first real candidate is accepted.
    def responder(email: str) -> SmtpProbeResult:
        if _UUID_LOCAL.match(email):
            return _reject(email)
        return _accept(email)

    service, prober = _service(responder)
    result = await service.verify(_request())

    assert result.status is VerificationStatus.VERIFIED
    assert result.verified_email == "alex.mercer@company.com"
    # Sentinel + exactly one candidate probe (early exit on first hit).
    assert len(prober.calls) == 2


async def test_catch_all_short_circuits() -> None:
    # Sentinel accepted => catch-all; no real candidates are probed.
    def responder(email: str) -> SmtpProbeResult:
        return _accept(email)

    service, prober = _service(responder)
    result = await service.verify(_request())

    assert result.status is VerificationStatus.CATCH_ALL
    assert result.verified_email is None
    assert len(prober.calls) == 1  # only the sentinel


async def test_not_found_on_hard_rejects() -> None:
    def responder(email: str) -> SmtpProbeResult:
        return _reject(email, code=550)

    service, _ = _service(responder)
    result = await service.verify(_request())

    assert result.status is VerificationStatus.NOT_FOUND


async def test_inconclusive_on_transient_codes() -> None:
    # Greylisting (4xx) must NOT be reported as NOT_FOUND.
    def responder(email: str) -> SmtpProbeResult:
        return _reject(email, code=451)

    service, _ = _service(responder)
    result = await service.verify(_request())

    assert result.status is VerificationStatus.INCONCLUSIVE


async def test_no_mx_records(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_mx(domain: str, **_: object) -> list[str]:
        return []

    monkeypatch.setattr(service_module, "resolve_mx_hosts", no_mx)
    service, _ = _service(_accept)
    result = await service.verify(_request())

    assert result.status is VerificationStatus.NO_MX_RECORDS


async def test_dns_error_degrades_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(domain: str, **_: object) -> list[str]:
        raise DnsResolutionError("SERVFAIL")

    monkeypatch.setattr(service_module, "resolve_mx_hosts", boom)
    service, _ = _service(_accept)
    result = await service.verify(_request())

    assert result.status is VerificationStatus.DNS_ERROR


async def test_proxy_error_during_catch_all() -> None:
    def responder(email: str) -> SmtpProbeResult:
        raise ProxyConnectionError("proxy down")

    service, _ = _service(responder)
    result = await service.verify(_request())

    assert result.status is VerificationStatus.PROXY_ERROR
