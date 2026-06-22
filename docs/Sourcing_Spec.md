# Component Specification: Sourcing Layer (LinkedIn Jobs via Apify)

Автономный слой поиска вакансий. Периодически опрашивает LinkedIn Jobs через
Apify-актора, дедуплицирует результаты и сохраняет новые вакансии для AI-пайплайна
сопоставления. Каждый **новый** постинг проходит дешёвый пре-скрин релевантности
`evaluate_job_relevance()` (Gemini Flash-Lite): score `< 55` → `FILTERED_OUT`,
иначе → `NEW`. Пре-скрин **fail-open**: ошибка LLM или пустой score → `NEW`, чтобы
сбой Gemini не отсеивал молча все вакансии (см.
[AI_Layer_Spec.md](./AI_Layer_Spec.md) §6).

## 1. Архитектура и границы

```
APScheduler (lifespan) ──► run_sourcing_job (tasks/sourcing_task.py)
                                  │
                 ┌────────────────┼─────────────────┐
                 ▼                ▼                  ▼
        ProfileRepository   fetch_jobs_from_apify   JobRepository
        get_all_profiles    (services/sourcing.py)  get_by_source_job_id
                                  │                   create
                                  ▼
                          ApifyClientAsync ──► curious_coder/linkedin-jobs-scraper
```

* **`app/services/sourcing.py`** — единственное место, где код общается с Apify.
  Слой DB-agnostic: возвращает «сырые» dict-элементы датасета и маппер в
  `JobCreate`. Никакого ручного HTTP — только `apify_client.ApifyClientAsync`.
* **`app/tasks/sourcing_task.py`** — шов между сервисом и персистентностью.
  Читает профили, запускает актора, сохраняет новые постинги.
* **`app/main.py`** (lifespan) — `AsyncIOScheduler` с триггером `cron`
  (ежедневно **03:00 UTC**), `max_instances=1`, `coalesce=True`. Стартует на старте
  приложения, гасится на выходе.
* **`SourcingSettings`** (`app/core/config.py`) — конфигурация слоя.

## 2. Входной контракт актора (важно!)

Актор `curious_coder/linkedin-jobs-scraper` — **URL-driven**. Его обязательный
вход — массив `urls` (страницы поиска LinkedIn), а **не** `searchTerms`/
`location`/`pages`. Полная схема входа:

| Поле            | Тип       | Обяз. | Назначение                                  |
| --------------- | --------- | :---: | ------------------------------------------- |
| `urls`          | string[]  |  ✅   | URL'ы результатов поиска LinkedIn Jobs      |
| `count`         | integer   |  —    | Верхняя граница числа вакансий              |
| `scrapeCompany` | boolean   |  —    | Доскрейпить профиль компании (дороже)       |
| `splitByLocation` / `splitCountry` | —  |  —    | Необязательные модификаторы                 |

Сервис строит URL из `(query, location)` функцией `_linkedin_search_url`, которая
percent-кодирует Boolean-запрос и локацию:

```
https://www.linkedin.com/jobs/search/?keywords=%22AI+Engineer%22&location=Israel&geoId=101620260
```

> Гостевой поиск LinkedIn надёжно фильтрует по региону только при наличии
> числового `geoId`; одного текстового `location` недостаточно — LinkedIn
> матчит его нестрого и часто отдаёт широкую / US-выдачу. `_resolve_geo_id`
> подставляет `geoId` для поддерживаемых локаций (см. `_LINKEDIN_GEO_IDS`);
> неизвестная локация отправляется только текстом.

Итоговый `run_input`:

```python
{
    "urls": [_linkedin_search_url(query, location)],
    "count": settings.pages * 25,   # у актора нет 'pages'; ~25 вакансий/страницу
    "scrapeCompany": True,          # доскрейп профиля → companyEmployeesCount
}
```

> Исторический баг: ранее отправлялся `{searchTerms, location, pages}`, и API
> отклонял каждый запуск с `Input is not valid: Field input.urls is required`
> (лог `sourcing_actor_failed` → `SourcingError`). Исправлено переходом на
> URL-driven вход.

## 3. Маппинг результата (`_to_job_create`)

Сырой элемент датасета → `JobCreate`. Читает только через `dict.get()`, поэтому
разреженный элемент никогда не падает:

| Поле БД           | Ключ Apify        | Защита                              |
| ----------------- | ----------------- | ----------------------------------- |
| `source_job_id`   | `job_id`          | нет id → элемент пропускается (лог) |
| `source_url`      | `job_url`         | fallback `apify://{job_id}`         |
| `company_name`    | `company`         | fallback `"Unknown"`, обрезка 255   |
| `job_title`       | `job_title`       | fallback `"Unknown"`, обрезка 255   |
| `description`     | `description`     | fallback `"No description provided."` |
| `location`        | `location`        | `None` если пусто, обрезка 255      |
| `employment_type` | `employmentType`  | `None` если пусто, обрезка 100      |
| `seniority_level` | `seniorityLevel`  | `None` если пусто, обрезка 100      |
| `salary`          | `salary`          | `""` → `None`, обрезка 255          |
| `employee_count`  | `companyEmployeesCount` | не-число/отриц. → `None` (только при `scrapeCompany`) |
| `company_linkedin_url` | `companyLinkedinUrl` | `None` если пусто, обрезка 512 (только при `scrapeCompany`) |

## 4. Конфигурация (`SourcingSettings`)

Читается из `.env`. `APIFY_TOKEN` валидируется при загрузке (fail-fast на старте,
как `AISettings`) — без него каждый прогон молча возвращал бы ошибку.

| Env                                  | Default                               | Назначение |
| ------------------------------------ | ------------------------------------- | ---------- |
| `APIFY_TOKEN`                        | — (**обязателен**)                    | Токен ApifyClientAsync |
| `APIFY_ACTOR_ID`                     | `curious_coder/linkedin-jobs-scraper` | ID актора |
| `SOURCING_LOCATION`                  | `Israel`                              | Локация-fallback, если профиль её не задал |
| `SOURCING_FORCE_DEFAULT_LOCATION`    | `false`                               | По умолчанию регион берётся из профиля; `true` — принудительно `SOURCING_LOCATION` для всех |
| `SOURCING_INTERVAL_HOURS`            | `24`                                  | Период запуска планировщика |
| `SOURCING_PAGES`                     | `1` (1–10)                            | Страницы результата → `count = pages*25` |
| `SOURCING_MAX_RUNS_PER_TASK`         | `1`                                   | Предохранитель бюджета: запусков актора за тик |

## 5. Модель стоимости и устойчивость

* **Cost-first.** Каждый запуск актора биллится как контейнер (не по строкам).
  Все тайтлы профиля OR-объединяются в один Boolean-запрос → **один запуск на
  профиль**. `max_runs_per_task` — жёсткий предохранитель: месячные запуски
  `<= (730 / interval_hours) * max_runs_per_task` (дефолты → ~30/мес).
* **Изоляция сбоев.** Любая ошибка актора/транспорта логируется и
  заворачивается в `SourcingError`, так что один упавший профиль не убивает
  планировщик.
* **Транзакционный радиус.** Постинги каждого профиля коммитятся своим батчем;
  каждая вставка — в `SAVEPOINT` (`begin_nested`), поэтому гонка
  `IntegrityError` по `source_job_id` теряет ровно одну строку.
* **Никогда не падает наверх.** Тело `run_sourcing_job` обёрнуто так, что
  непредвиденная ошибка логируется (`sourcing_job_failed`), но не пробрасывается
  в поток планировщика.

## 6. Структурное логирование (этапы)

`sourcing_job_started` → `sourcing_actor_started` → `sourcing_actor_finished` →
`sourcing_profile_done` → `sourcing_results_persisted` → `sourcing_job_finished`.
Ошибки: `sourcing_actor_failed`, `sourcing_no_profiles`,
`sourcing_run_budget_reached`, `sourcing_result_missing_job_id`.

## 7. Тесты

* `tests/test_sourcing.py` — фейковый `ApifyClientAsync`: happy path, проверка
  `run_input`, обёртка ошибок в `SourcingError`, отсутствующий датасет, маппер.
* `tests/test_sourcing_task.py` — персист + дедуп на повторном прогоне,
  устойчивость к ошибке запроса, fallback локации, no-profiles no-op.

## 8. Ручной прогон

```bash
cd backend
python -c "import asyncio; from app.tasks.sourcing_task import run_sourcing_job; asyncio.run(run_sourcing_job())"
```
