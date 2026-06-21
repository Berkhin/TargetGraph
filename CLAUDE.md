# AI Assistant Context & Development Rules

> Entry point for AI assistants working on **TargetGraph**. Read this first, then
> [ARCHITECTURE.md](ARCHITECTURE.md) for the runtime flow and [SKILLS.md](SKILLS.md)
> for the stack reference.

## What this project is

An end-to-end **cold-outreach** platform: source jobs (Apify LinkedIn) → cheap
LLM pre-screen → LangGraph matching pipeline (parallel tailored-CV ∥ Hunter.io
contact lookup → cover letter → reviewer loop) → send via Gmail REST API with a
client-generated PDF. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Tech Stack
- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.0 (async / `asyncpg`), Alembic,
  LangGraph, langchain-google-genai (Gemini), Pydantic v2, APScheduler.
- **Frontend:** React 19, TypeScript, Vite, TailwindCSS v4, Radix/shadcn-ui,
  TanStack Query, jsPDF.
- **External services:** Apify (sourcing), Hunter.io (contacts), Gmail API (send).

---

## Critical Code Style Rules

These are **binding** and override default behaviour.

### TypeScript / Frontend
- **Strict typing:** ALWAYS use `type` for data structures. NEVER use `interface`.
  Avoid `any`.
- **Controlled components.** Block submit buttons during requests
  (`disabled={isLoading}`) to prevent double-submits.
- **Contracts mirror the backend 1:1.** Frontend DTOs in `contracts/*` mirror the
  Pydantic schemas by field name (`job_title`, `match_score`, …). Keep them in sync
  when a schema changes.
- **Server state via TanStack Query** — no ad-hoc fetching in components; invalidate
  the right query keys after mutations.

### Python / Backend
- **Type hints:** start modules with `from __future__ import annotations`.
- **Async boundaries:** wrap synchronous blocking I/O (Google APIs, SMTP, file I/O)
  in `asyncio.to_thread()`. Never block the event loop.
- **Fail-soft / resilience:** wrap every external API call (Apify, Hunter, Gmail,
  Gemini) in `try/except` and degrade gracefully — return `None` / `[]`, or
  **fail-open** to `NEW` for the sourcing pre-screen. An external outage must never
  crash the scheduler, the pipeline, or the request.
- **Structured JSON logging.** No raw `print()`. Use the project logger with
  `extra={...}` event fields (e.g. `logger.info("sourcing_job_finished", extra=...)`).
- **Unit of Work:** service functions call `session.flush()`, **never**
  `session.commit()`. The request owns the transaction (FastAPI `get_session`
  dependency, or the streaming write-session). Do not add a second commit.
- **Repository pattern:** business logic talks to repositories that accept/return
  Pydantic models; keep SQLAlchemy objects out of the service/API layers.
- **LLM calls:** use `langchain-google-genai` with `.with_structured_output()` for
  scoring/extraction; model and temperature come from `AISettings`
  ([backend/app/core/config.py](backend/app/core/config.py)) — do not hard-code
  model names.

---

## Project map

```
backend/app/
  api/v1/         FastAPI routers: jobs.py, profiles.py, email_verification.py
  ai/             LangGraph: orchestrator.py (graph), nodes.py, state.py (GraphState)
  services/       sourcing.py (Apify), hunter_client.py, gmail_client.py,
                  orchestrator.py (run_pipeline / run_pipeline_stream),
                  email_verification/ (standalone, NOT in the matching pipeline)
  tasks/          sourcing_task.py (APScheduler cron job)
  repositories/   job_repository.py, profile_repository.py (Unit of Work)
  models/sql/     SQLAlchemy tables   models/schemas/  Pydantic DTOs   enums.py
  core/config.py  pydantic-settings classes (AI, Sourcing, Hunter, Gmail, …)
  main.py         lifespan + APScheduler wiring
frontend/src/
  contracts/      backend DTO mirror (type only)
  features/       jobs-board, profiles, cover-letters (feature-sliced)
  shared/         api client, errors, query keys
backend/migrations/versions/   Alembic chain (see docs/Migrations.md)
infra/            docker-compose.yml, Dockerfile
docs/             component specs (see index below)
```

## Key invariants (don't regress these)

- **Pre-screen is fail-open:** score `< 55` → `FILTERED_OUT`; error/`None` → `NEW`.
- **Score gate** default threshold is `50` in `GraphState` (configurable per run).
- **Recruiter contact = Hunter.io only** in the live pipeline. The SMTP
  email-verification engine is a standalone endpoint, not part of matching.
- **PDF is generated client-side** (jsPDF); there is no backend PDF library.
- **Gmail scope is `gmail.send`** (least-privilege, outbound only). No inbox
  parsing / Pub/Sub webhook exists (planned only).
- **No Celery/TaskIQ** — background work is APScheduler + FastAPI.
- **Recruiter contact lives on `job_postings`** — there are no `contacts` /
  `applications` tables.

---

## Documentation index (`docs/`)

| Doc | Scope |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Canonical end-to-end runtime flow |
| [SKILLS.md](SKILLS.md) | Stack & skills reference for assistants |
| [CHANGELOG.md](CHANGELOG.md) | Detailed change history |
| [docs/Architecture.md](docs/Architecture.md) | Infrastructure & operations (DB, Docker, scheduler, config) |
| [docs/AI_Layer_Spec.md](docs/AI_Layer_Spec.md) | LangGraph nodes, state, routing, models |
| [docs/Sourcing_Spec.md](docs/Sourcing_Spec.md) | Apify sourcing layer |
| [docs/Realtime_Matching_Spec.md](docs/Realtime_Matching_Spec.md) | WebSocket streaming protocol |
| [docs/API_Contracts.md](docs/API_Contracts.md) | REST/WS endpoints (implemented vs planned) |
| [docs/Data_Models.md](docs/Data_Models.md) / [docs/Migrations.md](docs/Migrations.md) | Schema & Alembic chain |
| [docs/Frontend_Spec.md](docs/Frontend_Spec.md) | SPA structure & data flows |
| [docs/Email_Verification_Spec.md](docs/Email_Verification_Spec.md) | Standalone SMTP verifier |
| [docs/Product_Requirements.md](docs/Product_Requirements.md) | Product vision (vision vs shipped) |
