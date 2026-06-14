"""Unit tests for request validation / domain normalisation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.email_verification.models import EmailVerificationRequest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Company.COM", "company.com"),
        ("https://company.com/careers", "company.com"),
        ("jobs@company.com", "company.com"),
        ("sub.company.co.uk", "sub.company.co.uk"),
        ("company.com.", "company.com"),
    ],
)
def test_domain_is_normalised(raw: str, expected: str) -> None:
    req = EmailVerificationRequest(first_name="A", last_name="B", domain=raw)
    assert req.domain == expected


@pytest.mark.parametrize("bad", ["", "not a domain", "localhost", "a.b-", "-a.com"])
def test_invalid_domain_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        EmailVerificationRequest(first_name="A", last_name="B", domain=bad)
