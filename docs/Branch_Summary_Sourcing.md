# Branch Summary: Sourcing + Frontend + Realtime Matching

Сводка всего, что реализовано в ветке `feat/sourcing-google-jobs` (фактически —
сорсинг через Apify LinkedIn, фронтенд, profiles API, real-time матчинг и
обогащение метаданными). Этот файл — точка входа в документацию ветки.

## Что вошло в ветку

### 1. Слой сорсинга (Apify LinkedIn Jobs) → [Sourcing_Spec.md](./Sourcing_Spec.md)
* `app/services/sourcing.py` — `fetch_jobs_from_apify` (URL-driven вход актора
  `curious_coder/linkedin-jobs-scraper`), маппер `_to_job_create`, `SourcingError`.
* `app/tasks/sourcing_task.py` — `run_sourcing_job`: один запуск актора на профиль,
  предохранитель бюджета, per-profile commit, `SAVEPOINT` на вставку, дедуп по
  `source_job_id`.
* `SourcingSettings` (`app/core/config.py`) — `APIFY_TOKEN` fail-fast, локация,
  интервал, `pages→count`, `max_runs_per_task`.
* `app/main.py` — `AsyncIOScheduler` в lifespan (`interval`, `max_instances=1`,
  `coalesce`).
* **Фикс input-бага:** актор требует `urls`, а не `searchTerms/location/pages`
  (ошибка `Field input.urls is required`).

### 2. Обогащение метаданными → [Job_Metadata_Spec.md](./Job_Metadata_Spec.md)
`location`, `employment_type`, `seniority_level`, `salary` (все nullable) сквозь
весь стек: SQLAlchemy → Pydantic DTO → маппер → миграция `d5e3f4a5b6c7` →
frontend-контракт → бейджи в `JobCard.tsx`.

### 3. Profiles API → [API_Contracts.md](./API_Contracts.md)
`app/api/v1/profiles.py`: `GET /api/v1/profiles`, `GET /api/v1/profiles/active`.
Репозиторий `ProfileRepository.get_all_profiles` (selectinload детей).

### 4. Real-time матчинг (WebSocket) → [Realtime_Matching_Spec.md](./Realtime_Matching_Spec.md)
`WS /api/v1/jobs/{job_id}/ws-match` + `run_pipeline_stream` в
`app/services/orchestrator.py` — стриминг пайплайна по узлам, короткоживущие
сессии, корректная обработка дисконнекта.

### 5. Frontend (React + Vite SPA) → [Frontend_Spec.md](./Frontend_Spec.md)
`frontend/` — feature-sliced SPA (jobs-board, profiles) на React 19 / Vite 8 /
TanStack Query / shadcn-ui; контракты зеркалят бэкенд 1:1.

### 6. Миграции → [Migrations.md](./Migrations.md)
Цепочка `2682ca1c3796 → b3f1a2c4d5e6 → d5e3f4a5b6c7 → e6f4a5b6c7d8`
(`source_job_id`, метаданные, `cover_letter_draft`). `scripts/reset_db.py`.

## Тесты ветки

* `tests/test_sourcing.py`, `tests/test_sourcing_task.py` — слой сорсинга.
* `tests/test_jobs_ws.py` — WebSocket-стрим матчинга.
* `tests/test_profiles_api.py`, `tests/test_profile_repository.py` — профили.
* `tests/test_config.py` — `SourcingSettings`.

## Связанные документы

* [Architecture.md](./Architecture.md) · [Data_Layer_Spec.md](./Data_Layer_Spec.md) ·
  [AI_Layer_Spec.md](./AI_Layer_Spec.md) · [EXAMPLES_JOB_MATCHING.md](./EXAMPLES_JOB_MATCHING.md)
