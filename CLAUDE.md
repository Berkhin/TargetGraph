# AI Assistant Context & Development Rules

## Tech Stack
- Backend: Python 3.11+, FastAPI, SQLAlchemy (Async), LangGraph, Pydantic v2.
- Frontend: React, TypeScript, TailwindCSS, shadcn/ui.

## Critical Code Style Rules

### TypeScript / Frontend
- Strict Typing: ALWAYS use `type` for defining data structures. NEVER use `interface`.
- UI Components: Use Controlled Components. Block buttons (`disabled={isLoading}`) during API requests to prevent double-submits.

### Python / Backend
- Type Hints: Use `from __future__ import annotations`.
- Asynchronous Boundaries: Wrap synchronous blocking I/O calls (e.g., Google API) in `asyncio.to_thread()`.
- Logging: Use structured JSON logging. No raw `print()`.
- Resilience / Fail-Soft: Wrap external API calls in `try/except`. Degrade gracefully on network failures (return `None` or `[]`).