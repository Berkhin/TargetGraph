# SKILLS / CONTEXT — Stack Reference

A focused reference of the technologies, libraries and patterns used in
**TargetGraph**, for AI assistants and new contributors. For the binding *rules*
see [CLAUDE.md](CLAUDE.md); for the runtime *flow* see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Languages & runtimes

| Skill | Where | Notes |
| --- | --- | --- |
| **Python 3.11+** | `backend/` | async-first; `from __future__ import annotations` everywhere |
| **TypeScript** | `frontend/` | strict; `type` only, no `interface`, avoid `any` |
| **Node.js** | `frontend/` tooling | Vite dev server / build; npm scripts |
| **SQL (PostgreSQL)** | schema/migrations | via SQLAlchemy + Alembic; SQLite in dev/test |

---

## Backend

### FastAPI
- Async routers under `backend/app/api/v1/` (`jobs`, `profiles`, `email_verification`).
- One WebSocket route (`/jobs/{id}/ws-match`). OpenAPI/Swagger auto-served at `/docs`.
- Dependency injection for the DB session (`get_session`); **the request owns the
  transaction** (Unit of Work) — services only `flush`.

### SQLAlchemy 2.0 (async) + Alembic
- `Mapped` / `mapped_column` typed models in `models/sql/`.
- `asyncpg` driver in prod; repository pattern isolates ORM objects from services.
- Alembic chain in `backend/migrations/versions/` — see [docs/Migrations.md](docs/Migrations.md).

### Pydantic v2
- DTOs/schemas in `models/schemas/`; `pydantic-settings` for config in `core/config.py`.
- `GraphState` (the LangGraph state) is a strict Pydantic model.

### LangGraph + langchain-google-genai (Gemini)
- Pipeline is a compiled `StateGraph` ([backend/app/ai/orchestrator.py](backend/app/ai/orchestrator.py)).
- Parallel fan-out via a router returning a **list** of node names; fan-in is implicit.
- `ChatGoogleGenerativeAI` with `.with_structured_output()` for scoring/extraction.
- Model + temperature are config-driven (`AISettings`); never hard-code model ids.
- See [docs/AI_Layer_Spec.md](docs/AI_Layer_Spec.md).

### Async & resilience patterns
- Blocking SDK calls (Google APIs, SMTP) → `asyncio.to_thread()`.
- Every external call is wrapped in `try/except` and **fails soft** (`None` / `[]`),
  or **fails open** to `NEW` for the sourcing pre-screen.
- Structured JSON logging with `extra={...}` event fields; no `print()`.

### Scheduling
- **APScheduler** `AsyncIOScheduler` wired into the FastAPI lifespan
  ([backend/app/main.py](backend/app/main.py)); sourcing runs on a daily cron
  trigger. No Celery/TaskIQ.

---

## Frontend

### React 19 + TypeScript + Vite
- Feature-sliced structure under `frontend/src/features/` (`jobs-board`,
  `profiles`, `cover-letters`); shared infra in `shared/`; backend DTO mirror in
  `contracts/`.
- See [docs/Frontend_Spec.md](docs/Frontend_Spec.md).

### UI & state
- **TailwindCSS v4** + **Radix/shadcn-ui** components (`components/ui/`).
- **TanStack Query** for all server state (cache, invalidation, statuses).
- **React Hook Form** for forms, **React Router** for routing, **sonner** for toasts,
  **axios** as the HTTP client, **lucide-react** for icons.

### Real-time & PDF
- WebSocket hook (`useMatchJobStream`) consumes the streaming match protocol.
- **jsPDF** renders the Markdown CV to PDF in the browser, then uploads base64 to
  the outreach endpoint (no backend PDF library).

---

## External integrations

| Service | Library / API | Role |
| --- | --- | --- |
| **Apify** | `apify-client` (`ApifyClientAsync`) | LinkedIn Jobs sourcing (URL-driven actor) |
| **Hunter.io** | v2 `domain-search` (httpx) | recruiter contact discovery (live pipeline) |
| **Gmail** | Google API client (OAuth 2.0) | outbound email; `gmail.send` scope |
| **Gemini** | langchain-google-genai | all LLM nodes + pre-screen |

---

## LLM-integration know-how

- **Two cost tiers**: cheap Flash-Lite for extraction/scoring/pre-screen; same model
  (or a Pro tier via env) for generation, with **higher temperature** for cover-letter
  prose (0.65) and **low** for CV (0.3) to avoid fabrication.
- **Self-correction**: a `reviewer` node fact-checks generated text for invented
  experience and loops the cover letter up to 3 times.
- **Structured output** for deterministic fields (scores, reasons) instead of parsing
  free text.
- **Fail-open pre-screen**: an LLM failure must not silently filter out every job.

---

## Deprecated / not in scope (do not reintroduce)

These appeared in early design notes but are **not** the current approach:

- ❌ **SerpAPI / Google Jobs** for sourcing — replaced by **Apify** LinkedIn actor.
- ❌ **SMTP permutation/catch-all verification inside the matching pipeline** — the
  verifier still exists as a *standalone* endpoint, but the live pipeline uses
  **Hunter.io** for contacts.
- ❌ **Backend PDF rendering** (WeasyPrint/ReportLab) — PDF is **client-side** (jsPDF).
- ❌ **Celery / TaskIQ** — background work is **APScheduler** + FastAPI.
- ❌ **Gmail inbox parsing / Pub/Sub webhooks** — not implemented (planned only);
  Gmail is outbound-only.
- ❌ Old model ids (`gemini-3.5-flash`, `gemini-2.x`) — default is `gemini-3.1-flash-lite`.
