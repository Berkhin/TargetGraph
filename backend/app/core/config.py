"""Application configuration.

Settings are loaded from environment variables (and an optional ``.env`` file),
which is the canonical configuration mechanism for the Docker Compose stack.

The email-verification engine deliberately keeps all of its tunables here so the
service object itself stays free of ``os.getenv`` calls and remains trivially
unit-testable (you can inject a custom :class:`EmailVerificationSettings`).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to the project-root ``.env`` so settings resolve identically
# whether a process is launched from the repo root, the ``backend`` directory,
# or via ``python -m scripts.*``. (config.py lives at backend/app/core/.)
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class EmailVerificationSettings(BaseSettings):
    """Tunables for :class:`app.services.email_verification.EmailVerificationService`.

    All SMTP traffic is routed through a SOCKS5 proxy. The proxy is expressed as
    a single URL (``socks5://user:pass@host:port``) to match the repository's
    ``.env.example`` and the ``python-socks`` ``Proxy.from_url`` contract.
    """

    model_config = SettingsConfigDict(
        env_prefix="EMAIL_VERIFY_",
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Proxy ---------------------------------------------------------------
    # Read from the shared PROXY_URL (no prefix) so the whole stack uses one
    # proxy definition. Empty string => proxy disabled (probing degrades).
    proxy_url: str = Field(
        default="",
        validation_alias="PROXY_URL",
        description="SOCKS5 proxy URL, e.g. socks5://user:pass@host:1080.",
    )

    @field_validator("proxy_url")
    @classmethod
    def _require_socks5_scheme(cls, value: str) -> str:
        """Enforce a SOCKS5 scheme.

        The "all SMTP via SOCKS5" requirement is only honoured if the URL is
        actually SOCKS5. ``Proxy.from_url`` would silently build an HTTP CONNECT
        tunnel from e.g. ``http://...``, leaking SMTP traffic outside SOCKS5 —
        so we reject anything but ``socks5://`` / ``socks5h://`` up front.
        An empty value means "proxy disabled" and is allowed (probing then
        fails closed with PROXY_ERROR rather than falling back to direct).
        """
        value = value.strip()
        if value and not value.startswith(("socks5://", "socks5h://")):
            raise ValueError(
                "PROXY_URL must use a socks5:// or socks5h:// scheme; "
                f"got {value.split('://', 1)[0]!r}"
            )
        return value

    # --- SMTP envelope -------------------------------------------------------
    smtp_port: int = Field(
        default=25,
        ge=1,
        le=65535,
        description="Port to reach the MX server on (25 for inbound SMTP).",
    )
    helo_hostname: str = Field(
        default="mail.targetgraph.io",
        description="Hostname presented in the HELO/EHLO command.",
    )
    mail_from: str = Field(
        default="verify@targetgraph.io",
        description="Envelope sender used in MAIL FROM during probing.",
    )

    # --- Timeouts & limits (container-friendly defaults) ---------------------
    dns_timeout_seconds: float = Field(
        default=5.0, gt=0, description="Per-attempt DNS resolution timeout."
    )
    dns_lifetime_seconds: float = Field(
        default=10.0, gt=0, description="Total DNS resolution budget."
    )
    smtp_connect_timeout_seconds: float = Field(
        default=15.0,
        gt=0,
        description="Timeout for opening the proxied socket to the MX server.",
    )
    smtp_command_timeout_seconds: float = Field(
        default=15.0, gt=0, description="Timeout for each SMTP command."
    )
    max_candidates: int = Field(
        default=12,
        ge=1,
        le=50,
        description="Upper bound on generated candidates probed per request.",
    )

    @property
    def proxy_enabled(self) -> bool:
        """Whether a SOCKS5 proxy has been configured."""
        return bool(self.proxy_url.strip())


@lru_cache
def get_email_verification_settings() -> EmailVerificationSettings:
    """Return a process-wide cached settings instance."""
    return EmailVerificationSettings()


class DatabaseSettings(BaseSettings):
    """PostgreSQL / SQLAlchemy connection settings.

    The async URL is assembled from the discrete ``POSTGRES_*`` variables that
    already drive the Docker Compose Postgres service, with a single
    ``DATABASE_URL`` escape hatch for environments that supply a full DSN.
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    postgres_user: str = Field(default="postgres", validation_alias="POSTGRES_USER")
    postgres_password: str = Field(default="", validation_alias="POSTGRES_PASSWORD")
    postgres_host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    postgres_db: str = Field(default="targetgraph", validation_alias="POSTGRES_DB")

    # Full DSN override (e.g. postgresql+asyncpg://...). Empty => assemble below.
    database_url: str = Field(default="", validation_alias="DATABASE_URL")

    echo: bool = Field(default=False, validation_alias="DB_ECHO")
    pool_size: int = Field(default=5, ge=1, validation_alias="DB_POOL_SIZE")
    max_overflow: int = Field(default=10, ge=0, validation_alias="DB_MAX_OVERFLOW")

    @property
    def async_url(self) -> str:
        """The SQLAlchemy async (asyncpg) connection URL."""
        if self.database_url:
            return self.database_url
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_database_settings() -> DatabaseSettings:
    """Return a process-wide cached database settings instance."""
    return DatabaseSettings()


class AISettings(BaseSettings):
    """LLM / Gemini settings for the LangGraph matching pipeline.

    The API key is read from ``GEMINI_API_KEY`` to match the repository's
    ``.env`` (the official ``langchain-google-genai`` integration also honours
    ``GOOGLE_API_KEY``/``GEMINI_API_KEY`` from the environment, but we pass the
    key explicitly so the client never depends on ambient process state).
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    gemini_api_key: str = Field(
        default="",
        validation_alias="GEMINI_API_KEY",
        description="Google Gemini API key (Generative Language API).",
    )
    gemini_model: str = Field(
        default="gemini-3.1-flash-lite",
        validation_alias="GEMINI_MODEL",
        description="Gemini model id used by ChatGoogleGenerativeAI.",
    )
    gemini_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        validation_alias="GEMINI_TEMPERATURE",
        description="Sampling temperature; 0.0 for deterministic extraction.",
    )

    @model_validator(mode="after")
    def _require_api_key(self) -> "AISettings":
        """Fail fast on a missing key.

        Without this, ``ChatGoogleGenerativeAI`` still constructs with an empty
        key and only fails (with ``Unauthenticated``) on every ``ainvoke`` —
        which the node swallows, so the pipeline silently extracts nothing. We
        surface the misconfiguration at settings-load time instead. Unit tests
        that don't need a real key should construct ``AISettings(
        gemini_api_key="test-key")`` directly rather than via ``get_ai_settings``.
        """
        if not self.gemini_api_key.strip():
            raise ValueError(
                "GEMINI_API_KEY is required but not set. Add it to your .env file."
            )
        return self


@lru_cache
def get_ai_settings() -> AISettings:
    """Return a process-wide cached AI settings instance."""
    return AISettings()
