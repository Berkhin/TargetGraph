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

# The ``backend`` package root (config.py lives at backend/app/core/). Relative
# SQLite file paths are anchored here so every entry point — uvicorn (launched
# from ``backend``), Alembic (alembic.ini lives in ``backend``), and ad-hoc
# scripts launched from anywhere — opens the *same* file. Otherwise a relative
# ``sqlite:///./dev.db`` silently resolves against the current directory, so a
# task run from the repo root and the API run from ``backend`` end up on two
# different databases.
_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _absolutize_sqlite_url(url: str) -> str:
    """Anchor a relative SQLite file path in ``url`` to :data:`_BACKEND_DIR`.

    No-ops for non-SQLite URLs, in-memory databases, and already-absolute
    paths, so it is safe to apply to any ``DATABASE_URL``.
    """
    scheme, sep, path = url.partition(":///")
    if not sep or "sqlite" not in scheme:
        return url
    if path.startswith(":memory:") or not path:
        return url
    candidate = Path(path)
    if candidate.is_absolute():
        return url
    absolute = (_BACKEND_DIR / path).resolve()
    return f"{scheme}:///{absolute.as_posix()}"


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
        """The SQLAlchemy async connection URL.

        A relative SQLite path is rewritten to an absolute one anchored at the
        ``backend`` directory so the database file is identical regardless of the
        process's working directory (see :func:`_absolutize_sqlite_url`).
        """
        if self.database_url:
            return _absolutize_sqlite_url(self.database_url)
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
    # Two model tiers (kept separate so generation can be bumped to a pro model
    # later via env, without touching analysis). Both default to the *lite* model:
    # on the free tier flash-lite allows ~500 requests/day, vs only 20/day for
    # gemini-3.5-flash and 0/day for the pro tier — so lite is the only id that is
    # actually usable without billing. (1.5-family models remain forbidden.)
    #   * flash tier — structured/analytical: extraction, matching, review, pre-screen.
    #   * generation tier — cover letter + tailored CV.
    gemini_model: str = Field(
        default="gemini-3.1-flash-lite",
        validation_alias="GEMINI_MODEL",
        description="Analytical-tier model id for extraction, matching, review, pre-screen.",
    )
    # Defaults to flash-lite (free-tier-friendly). Set to a pro id
    # (e.g. gemini-3.1-pro-preview) once billing is enabled for higher-quality prose.
    gemini_generation_model: str = Field(
        default="gemini-3.1-flash-lite",
        validation_alias="GEMINI_GENERATION_MODEL",
        description="Model id for cover-letter and tailored-CV generation.",
    )
    gemini_max_retries: int = Field(
        default=2,
        ge=0,
        le=6,
        validation_alias="GEMINI_MAX_RETRIES",
        description="Max client retries on transient/quota errors; low so a hard "
        "quota (limit=0) fails fast instead of backing off for minutes.",
    )
    gemini_requests_per_minute: int = Field(
        default=15,
        ge=1,
        validation_alias="GEMINI_REQUESTS_PER_MINUTE",
        description="Client-side cap on Gemini calls per minute, shared across all "
        "graph nodes and the sourcing pre-screen, to stay under the free-tier RPM "
        "quota (flash-lite = 15/min). Lower it if you still see 429s.",
    )
    # The reviewer fact-checks the cover letter and can trigger up to 3 redraft
    # passes — i.e. several extra LLM calls per job. Off by default to conserve the
    # tiny free-tier daily quota; enable it when quota (billing) is not a concern.
    ai_enable_review: bool = Field(
        default=False,
        validation_alias="AI_ENABLE_REVIEW",
        description="Run the reviewer + revision loop (extra LLM calls per job).",
    )
    gemini_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        validation_alias="GEMINI_TEMPERATURE",
        description="Sampling temperature for analytical/structured nodes; 0.0 = deterministic.",
    )
    # Generation temperatures are split on purpose: the tailored CV must not
    # hallucinate facts about the candidate's experience (low temp), while the
    # cover letter benefits from a livelier, more natural voice (higher temp).
    gemini_cover_letter_temperature: float = Field(
        default=0.65,
        ge=0.0,
        le=2.0,
        validation_alias="GEMINI_COVER_LETTER_TEMPERATURE",
        description="Sampling temperature for cover-letter drafting (natural voice).",
    )
    gemini_tailored_cv_temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        validation_alias="GEMINI_TAILORED_CV_TEMPERATURE",
        description="Sampling temperature for tailored-CV drafting (factual, low-hallucination).",
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


class SourcingSettings(BaseSettings):
    """Settings for the autonomous job-sourcing layer (LinkedIn Jobs via Apify).

    Drives :func:`app.services.sourcing.fetch_jobs_from_apify` and the periodic
    :func:`app.tasks.sourcing_task.run_sourcing_job` task. The ``APIFY_TOKEN`` is
    required and validated at load time so the application fails fast at start-up
    rather than silently no-op'ing every scheduled run (mirrors :class:`AISettings`).

    Cost model (this drives the whole design): every actor run spins up an Apify
    container, which is what we are billed for — *not* the number of result rows.
    So the task makes at most ONE actor run per profile (all target titles are
    OR-joined into a single Boolean query) and ``max_runs_per_task`` plus
    ``pages`` keep a single tick comfortably inside the free $5/month tier.
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    apify_token: str = Field(
        default="",
        validation_alias="APIFY_TOKEN",
        description="Apify API token used by ApifyClientAsync.",
    )
    apify_actor_id: str = Field(
        default="curious_coder/linkedin-jobs-scraper",
        validation_alias="APIFY_ACTOR_ID",
        description="Apify actor that scrapes LinkedIn Jobs.",
    )
    default_location: str = Field(
        default="Israel",
        validation_alias="SOURCING_LOCATION",
        description="Fallback search location when a profile has none set.",
    )
    force_default_location: bool = Field(
        default=False,
        validation_alias="SOURCING_FORCE_DEFAULT_LOCATION",
        description=(
            "When true, every run ignores each profile's preferred location and "
            "uses default_location instead. Off by default: the search region is "
            "taken from the candidate's profile (e.g. 'Israel'), falling back to "
            "default_location only when the profile sets none. Set true to force a "
            "single region with dense LinkedIn coverage for every profile."
        ),
    )
    interval_hours: int = Field(
        default=24,
        ge=1,
        validation_alias="SOURCING_INTERVAL_HOURS",
        description=(
            "How often the sourcing job runs, in hours. Drives monthly Apify "
            "spend together with pages and max_runs_per_task — see the budget "
            "note on max_runs_per_task."
        ),
    )
    pages: int = Field(
        default=1,
        ge=1,
        le=10,
        validation_alias="SOURCING_PAGES",
        description=(
            "Result pages the Apify actor scrapes per run (the actor's 'pages' "
            "input). Kept at 1 to minimise per-run compute and stay inside the "
            "free $5/month tier; raise only if you have budget headroom."
        ),
    )
    max_runs_per_task: int = Field(
        default=1,
        ge=1,
        validation_alias="SOURCING_MAX_RUNS_PER_TASK",
        description=(
            "Hard ceiling on Apify actor runs started in a single task tick "
            "(one run per profile). Each run bills a container, so this bounds "
            "monthly spend deterministically: monthly runs <= "
            "(730 / interval_hours) * max_runs_per_task. With the defaults "
            "(24h, 1) that is ~30 runs/month. Keep the product under your tier."
        ),
    )

    @model_validator(mode="after")
    def _require_api_key(self) -> "SourcingSettings":
        """Fail fast on a missing token.

        Without a token every Apify call returns an error, so a scheduled run
        would loop, log failures, and add nothing. We surface the
        misconfiguration at settings-load (start-up) time instead. Unit tests
        that don't need a real token should construct ``SourcingSettings(
        apify_token="test-token")`` directly rather than via ``get_sourcing_settings``.
        """
        if not self.apify_token.strip():
            raise ValueError(
                "APIFY_TOKEN is required but not set. Add it to your .env file."
            )
        return self


@lru_cache
def get_sourcing_settings() -> SourcingSettings:
    """Return a process-wide cached sourcing settings instance."""
    return SourcingSettings()


class HunterSettings(BaseSettings):
    """Settings for the Hunter.io email-discovery integration (cold outreach).

    Drives :class:`app.services.hunter_client.HunterClient`, which finds the
    email addresses of recruiters / hiring managers at a target company from its
    domain. Unlike the AI and sourcing settings, the key is *not* validated at
    load time: cold outreach is an optional pipeline stage, so a missing key
    degrades to an empty contact list (logged) rather than failing start-up.
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    hunter_api_key: str = Field(
        default="",
        validation_alias="HUNTER_API_KEY",
        description="Hunter.io API key for the v2 domain-search endpoint.",
    )


@lru_cache
def get_hunter_settings() -> HunterSettings:
    """Return a process-wide cached Hunter settings instance."""
    return HunterSettings()


class GmailSettings(BaseSettings):
    """Settings for cold-outreach email sending via the Gmail API (OAuth 2.0).

    Drives :class:`app.services.gmail_client.GmailClient`. Two on-disk artefacts:
    ``credentials.json`` (the OAuth *client secrets* downloaded from Google Cloud
    for a Desktop App) and ``token.json`` (the user's authorised token, created on
    the first consent and refreshed thereafter). Both are resolved relative to the
    ``backend`` directory so they're found regardless of the process's CWD, and
    both are git-ignored — they are secrets.
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    gmail_credentials_file: str = Field(
        default="credentials.json",
        validation_alias="GMAIL_CREDENTIALS_FILE",
        description="OAuth client-secrets file (Desktop App) from Google Cloud.",
    )
    gmail_token_file: str = Field(
        default="token.json",
        validation_alias="GMAIL_TOKEN_FILE",
        description="Authorised-user token, created/refreshed by the OAuth flow.",
    )

    def _anchor(self, path: str) -> str:
        """Resolve a possibly-relative path against the ``backend`` directory."""
        candidate = Path(path)
        if candidate.is_absolute():
            return str(candidate)
        return str((_BACKEND_DIR / candidate).resolve())

    @property
    def credentials_path(self) -> str:
        """Absolute path to the OAuth client-secrets file."""
        return self._anchor(self.gmail_credentials_file)

    @property
    def token_path(self) -> str:
        """Absolute path to the authorised-user token file."""
        return self._anchor(self.gmail_token_file)


@lru_cache
def get_gmail_settings() -> GmailSettings:
    """Return a process-wide cached Gmail settings instance."""
    return GmailSettings()


class OutreachSettings(BaseSettings):
    """Settings for cold-outreach email *content* (the disclaimer postscript).

    Every recruiter email gets an auto-appended "Engineering Disclaimer" that
    advertises the system that sent it and links to its source. Only the
    repository URL varies per operator, so it is the single tunable here.
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    github_url: str = Field(
        default="https://github.com/Berkhin/TargetGraph",
        validation_alias="OUTREACH_GITHUB_URL",
        description="Repository URL advertised in the outreach disclaimer postscript.",
    )


@lru_cache
def get_outreach_settings() -> OutreachSettings:
    """Return a process-wide cached outreach settings instance."""
    return OutreachSettings()


class CORSSettings(BaseSettings):
    """Cross-Origin Resource Sharing policy for the browser SPA frontend.

    The Vite dev server runs on a different origin (``http://localhost:5173``)
    than the API (``http://localhost:8000``), so the browser blocks calls unless
    the API echoes the appropriate ``Access-Control-Allow-*`` headers. Origins
    are configurable via a comma-separated ``CORS_ALLOW_ORIGINS`` for staging /
    production deployments.
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    allow_origins_raw: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="CORS_ALLOW_ORIGINS",
        description="Comma-separated list of allowed browser origins.",
    )

    @property
    def allow_origins(self) -> list[str]:
        """Parsed, de-blanked list of allowed origins."""
        return [o.strip() for o in self.allow_origins_raw.split(",") if o.strip()]


@lru_cache
def get_cors_settings() -> CORSSettings:
    """Return a process-wide cached CORS settings instance."""
    return CORSSettings()
