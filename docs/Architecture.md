# Infrastructure & Operations

> The **end-to-end application flow** (sourcing → pre-screen → LangGraph → outreach)
> lives in the canonical [../ARCHITECTURE.md](../ARCHITECTURE.md). This document
> covers infrastructure and operational concerns: database, migrations, scheduling,
> configuration, deployment and logging.

## 1. Database

* **DBMS:** PostgreSQL (prod, in Docker); SQLite for local dev/tests.
* **ORM:** SQLAlchemy 2.0, async engine (`asyncpg`), typed `Mapped` / `mapped_column`.
* **Access pattern:** Repository — services depend on `JobRepository` /
  `ProfileRepository`, which accept and return Pydantic models and encapsulate ORM
  objects.
* **Transactions (Unit of Work):** the **request** owns the transaction (FastAPI
  `get_session` dependency, or the streaming write-session). Service functions only
  `flush`, never `commit`.
* **Migrations:** Alembic, linear chain in `backend/migrations/versions/`,
  `alembic.ini` in `backend/`. See [Migrations.md](./Migrations.md) and
  [Data_Models.md](./Data_Models.md).

## 2. Scheduling

* **APScheduler** `AsyncIOScheduler`, wired into the FastAPI lifespan
  ([backend/app/main.py](../backend/app/main.py)).
* Single job: `run_sourcing_job` on a **cron** trigger (daily **03:00 UTC**),
  `max_instances=1`, `coalesce=True`. Started on app startup, shut down on exit.
* **No external task queue** (no Celery / TaskIQ). Long work in request handlers is
  awaited directly (matching) or streamed (WebSocket).

## 3. Configuration

`pydantic-settings` classes in [backend/app/core/config.py](../backend/app/core/config.py),
loaded from `.env`:

| Settings class | Covers | Notable env |
| --- | --- | --- |
| `AISettings` | Gemini model/temperature/retry | `GEMINI_API_KEY` (required), `GEMINI_MODEL`, `GEMINI_GENERATION_MODEL` |
| `SourcingSettings` | Apify sourcing | `APIFY_TOKEN` (fail-fast at startup), `APIFY_ACTOR_ID`, location/interval/pages |
| `HunterSettings` | contact discovery | `HUNTER_API_KEY` (optional) |
| `GmailSettings` | email send | `GMAIL_CREDENTIALS_FILE`, `GMAIL_TOKEN_FILE` |
| `OutreachSettings` | email postscript | engineering-disclaimer GitHub URL |
| `EmailVerificationSettings` | standalone SMTP verifier | SOCKS5 proxy, SMTP envelope, timeouts |
| `DatabaseSettings` | connection | `DATABASE_URL` |
| `CORSSettings` | browser origin allowlist | dev origin `http://localhost:5173` |

Required keys (`GEMINI_API_KEY`, `APIFY_TOKEN`) are validated at startup so a
misconfiguration fails fast rather than silently degrading every run.

## 4. Deployment

* **Docker:** [infra/docker-compose.yml](../infra/docker-compose.yml) and
  [backend/Dockerfile](../backend/Dockerfile).
* **Backend:** `uvicorn app.main:app` (OpenAPI/Swagger at `/docs`).
* **Frontend:** Vite build served as a static SPA; dev server on `:5173`
  (allowlisted in `CORSSettings`).

## 5. Logging & observability

* **Structured JSON logging** throughout — no raw `print()`. Events carry an
  `extra={...}` payload (e.g. `sourcing_job_started`, `sourcing_results_persisted`,
  `find_recruiter_contact.failed`).
* **Fail-soft posture:** external failures are logged and degraded, never raised to
  the scheduler or the top of a request. See [../CLAUDE.md](../CLAUDE.md).

## 6. AI orchestration (pointer)

The LangGraph pipeline (nodes, routing, parallel fan-out, revision loop, per-node
Gemini models) is specified in [AI_Layer_Spec.md](./AI_Layer_Spec.md) and
summarised in [../ARCHITECTURE.md](../ARCHITECTURE.md §3). It is intentionally
**DB-agnostic**: no DB connection is held during the graph run.
