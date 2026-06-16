"""Tests for proxy configuration safety and DB URL resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import (
    DatabaseSettings,
    EmailVerificationSettings,
    _absolutize_sqlite_url,
    _BACKEND_DIR,
)


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


def test_relative_sqlite_url_anchored_to_backend_dir() -> None:
    # A relative sqlite path must resolve to the SAME file regardless of cwd, so
    # the API (run from backend/) and a task run from the repo root share one DB.
    expected = (_BACKEND_DIR / "dev.db").resolve().as_posix()
    assert (
        _absolutize_sqlite_url("sqlite+aiosqlite:///./dev.db")
        == f"sqlite+aiosqlite:///{expected}"
    )
    assert (
        DatabaseSettings(DATABASE_URL="sqlite+aiosqlite:///./dev.db").async_url
        == f"sqlite+aiosqlite:///{expected}"
    )


def test_absolutize_noops_for_memory_and_absolute_and_non_sqlite() -> None:
    # In-memory, already-absolute, and non-sqlite URLs are returned unchanged.
    assert (
        _absolutize_sqlite_url("sqlite+aiosqlite:///:memory:")
        == "sqlite+aiosqlite:///:memory:"
    )
    abs_path = (Path("/tmp/x.db")).resolve()  # noqa: S108 - test literal only
    abs_url = f"sqlite+aiosqlite:///{abs_path.as_posix()}"
    assert _absolutize_sqlite_url(abs_url) == abs_url
    pg = "postgresql+asyncpg://u:p@host:5432/db"
    assert _absolutize_sqlite_url(pg) == pg
