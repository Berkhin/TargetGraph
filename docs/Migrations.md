# Database Migrations (Alembic)

Все изменения структуры БД версионируются Alembic. Скрипты лежат в
`backend/migrations/versions/`, `alembic.ini` — в `backend/`.

## Цепочка ревизий (линейная)

```
2682ca1c3796  initial_schema_jobs_and_master_profile   (down_revision = None)
      │
b3f1a2c4d5e6  add_source_job_id_to_job_postings
      │
d5e3f4a5b6c7  add_job_metadata
      │
e6f4a5b6c7d8  add_cover_letter_draft                    (head)
```

| Revision        | Что добавляет | Колонки |
| --------------- | ------------- | ------- |
| `2682ca1c3796`  | Базовая схема: `job_postings` + master-profile (профиль, опыт, навыки) | — |
| `b3f1a2c4d5e6`  | Дедуп сорсинга | `source_job_id` (`String(512)`, nullable, **unique**, index) |
| `d5e3f4a5b6c7`  | Метаданные вакансии | `location`, `employment_type`, `seniority_level`, `salary` (все nullable) |
| `e6f4a5b6c7d8`  | Черновик письма | `cover_letter_draft` (`Text`, nullable) |

> `d5e3f4a5b6c7` и `e6f4a5b6c7d8` написаны вручную в стиле соседних ревизий.
> `e6f4a5b6c7d8` бэкфиллит колонку `cover_letter_draft`, которая была добавлена в
> ORM-модель вместе с AI `draft_documents`, но не была захвачена миграцией — БД,
> собранная из миграций, падала на `SELECT ... cover_letter_draft` с
> `no such column`.

## Команды

```bash
cd backend
alembic upgrade head                              # применить всё до головы
alembic revision --autogenerate -m "описание"     # сгенерировать новую ревизию
alembic downgrade -1                              # откатить на одну ревизию
alembic current                                   # текущая ревизия БД
alembic history                                   # история цепочки
```

## Сброс локальной БД (dev)

`backend/scripts/reset_db.py` — пересоздаёт локальную БД с нуля для разработки
(SQLite-файлы `*.db` игнорируются git'ом). Используйте при расхождении схемы и
миграций в dev-окружении.
