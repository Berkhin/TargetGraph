"""Tests for proxy configuration safety."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import EmailVerificationSettings


@pytest.mark.parametrize("url", ["socks5://h:1080", "socks5h://user:pass@h:1080"])
def test_socks5_schemes_accepted(url: str) -> None:
    settings = EmailVerificationSettings(PROXY_URL=url)
    assert settings.proxy_enabled is True


def test_empty_proxy_is_allowed_but_disabled() -> None:
    settings = EmailVerificationSettings(PROXY_URL="")
    assert settings.proxy_enabled is False


@pytest.mark.parametrize(
    "url",
    ["http://proxy:3128", "https://proxy:3128", "socks4://h:1080", "h:1080"],
)
def test_non_socks5_schemes_rejected(url: str) -> None:
    # Prevents silently tunnelling SMTP over HTTP CONNECT / SOCKS4.
    with pytest.raises(ValidationError):
        EmailVerificationSettings(PROXY_URL=url)
