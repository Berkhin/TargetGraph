# TargetGraph

**An end-to-end cold-outreach platform for job seekers.** TargetGraph sources job
postings, scores them against your profile with an LLM pipeline, finds the hiring
manager's contact, generates a tailored CV and a personalised cover letter, and
sends the package by email — instead of filling in endless web forms.

```
Apify (LinkedIn)  →  Pre-screen (Gemini Flash)  →  LangGraph pipeline  →  Gmail REST
  sourcing            cheap relevance gate          parallel CV ∥ Hunter    + client PDF
                      FILTERED_OUT / NEW            + cover letter + reviewer
```

> 📐 Full design: [ARCHITECTURE.md](ARCHITECTURE.md) ·
> 🤖 AI-assistant rules: [CLAUDE.md](CLAUDE.md) ·
> 🧰 Stack reference: [SKILLS.md](SKILLS.md) ·
> 📜 History: [CHANGELOG.md](CHANGELOG.md)

---

## Features

- **Automated sourcing** — scheduled Apify LinkedIn Jobs scrape, deduped by source id.
- **Cheap pre-screening** — a Gemini Flash-Lite relevance gate drops obvious misses
  (`FILTERED_OUT`) before the expensive pipeline runs (fail-open by design).
- **LangGraph matching** — extract requirements → score → **parallel** tailored-CV
  generation and Hunter.io recruiter lookup → personalised cover letter → a strict
  reviewer with a bounded revision loop.
- **Real-time execution telemetry** — WebSocket streaming pushes state changes from
  the parallel LangGraph nodes straight to the UI, node-by-node, with no polling.
- **One-click outreach** — client-rendered PDF CV emailed to the recruiter via the
  Gmail API; the posting is stamped `applied_at`.

## Tech stack

| | |
| --- | --- |
| **Backend** | Python 3.11+, FastAPI, SQLAlchemy 2.0 async (`asyncpg`), Alembic, LangGraph, langchain-google-genai (Gemini), Pydantic v2, APScheduler |
| **Frontend** | React 19, TypeScript, Vite, TailwindCSS v4, Radix/shadcn-ui, TanStack Query, jsPDF |
| **External** | Apify (sourcing) · Hunter.io (contacts) · Gmail API (send) |
| **Infra** | PostgreSQL (prod) / SQLite (dev), Docker Compose |

## Repository layout

```
backend/    FastAPI app, LangGraph pipeline, services, repositories, Alembic migrations
frontend/   React + Vite SPA (feature-sliced)
infra/      docker-compose.yml, Dockerfile
docs/       component specifications (see CLAUDE.md for the index)
```

---

## Quick start

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .                                     # or: pip install -r requirements.txt
cp .env.example .env                                 # fill in keys (see below)
alembic upgrade head                                 # apply migrations
uvicorn app.main:app --reload                        # http://localhost:8000  (docs at /docs)
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
npm run build    # tsc -b && vite build
```

### Docker

```bash
docker compose -f infra/docker-compose.yml up --build
```

## Configuration (key env vars)

Settings are defined in [backend/app/core/config.py](backend/app/core/config.py)
(`pydantic-settings`). The most important:

| Var | Used by | Notes |
| --- | --- | --- |
| `GEMINI_API_KEY` | AI pipeline | required; Gemini Generative Language API |
| `GEMINI_MODEL` / `GEMINI_GENERATION_MODEL` | AI pipeline | default `gemini-3.1-flash-lite`; point at a Pro tier to upgrade |
| `APIFY_TOKEN` | sourcing | required; validated at startup |
| `HUNTER_API_KEY` | contact discovery | optional; without it, outreach has no recruiter contact |
| `GMAIL_CREDENTIALS_FILE` | email send | OAuth 2.0 Desktop-App JSON downloaded from the Google Cloud Console (git-ignored) |
| `GMAIL_TOKEN_FILE` | email send | cached OAuth token, written on first consent (git-ignored) |
| `DATABASE_URL` | persistence | PostgreSQL (prod) / SQLite (dev) |

## Testing

```bash
cd backend && pytest
```

See [CLAUDE.md](CLAUDE.md) before contributing — it carries the binding code-style
rules (`type` over `interface`, `asyncio.to_thread` for blocking I/O, fail-soft
external calls, Unit-of-Work transaction ownership).
