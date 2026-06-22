# Component Specification: Job Metadata Enrichment

Обогащение вакансий метаданными из LinkedIn-скрапера (`location`,
`employment_type`, `seniority_level`, `salary`) для усиления контекста ИИ и UI.
Все поля строго опциональны (`nullable`), чтобы не уронить приложение на старых
данных и разреженных результатах скрапера.

## 1. Затронутые слои (single source of truth → вниз по стеку)

| Слой              | Файл                                          | Изменение |
| ----------------- | --------------------------------------------- | --------- |
| SQLAlchemy        | `app/models/sql/job_posting.py`               | 4 колонки `nullable=True` |
| Pydantic DTO      | `app/models/schemas/job.py`                   | поля в `JobBase` (→ `JobCreate`/`JobRead`) + `JobUpdate` |
| Маппер            | `app/services/sourcing.py` `_to_job_create`   | извлечение из dict скрапера |
| Миграция          | `migrations/versions/d5e3f4a5b6c7_add_job_metadata.py` | `add_column` ×4 |
| Frontend контракт | `frontend/src/contracts/job.ts`               | 4 поля `string \| null` |
| Frontend UI       | `frontend/src/features/jobs-board/ui/JobCard.tsx` | shadcn `Badge` под каждое поле |

## 2. Схема полей

| Поле              | Тип SQL       | DTO            | Источник (ключ Apify) |
| ----------------- | ------------- | -------------- | --------------------- |
| `location`        | `String(255)` | `str \| None`  | `location`            |
| `employment_type` | `String(100)` | `str \| None`  | `employmentType`      |
| `seniority_level` | `String(100)` | `str \| None`  | `seniorityLevel`      |
| `salary`          | `String(255)` | `str \| None`  | `salary`              |
| `employee_count`  | `Integer`     | `int \| None`  | `companyEmployeesCount` (нужен `scrapeCompany`) |
| `company_linkedin_url` | `String(512)` | `str \| None` | `companyLinkedinUrl` (нужен `scrapeCompany`) |

## 3. Правила маппинга (защита от падений)

* Чтение только через `raw.get(...)` — отсутствие ключа даёт `None`, не KeyError.
* `salary`: пустая строка `""` нормализуется в `None`
  (`salary = salary_raw if salary_raw else None`).
* Все строки обрезаются по `max_length` колонки перед инициализацией `JobCreate`.

## 4. Frontend

`JobCard.tsx` рендерит каждое непустое поле как `<Badge variant="outline">`
(`location`, `employment_type`, `seniority_level`, `salary`, `employee_count` →
«N сотрудников»); `null`-значения не выводятся. `company_linkedin_url` выводится
не бейджем, а отдельной кнопкой-иконкой (LinkedIn компании) в `CardAction`, если
не `null`. Контракт `Job` в `contracts/job.ts` зеркалит `JobRead` 1:1.

## 5. Миграция

```bash
cd backend
alembic revision --autogenerate -m "add_job_metadata"   # авто-генерация (для справки)
alembic upgrade head                                     # применение
```

Миграция `d5e3f4a5b6c7` (revises `b3f1a2c4d5e6`) написана вручную в стиле
соседних ревизий: `upgrade` добавляет 4 nullable-колонки, `downgrade` их удаляет.
