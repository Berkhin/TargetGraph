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
e6f4a5b6c7d8  add_cover_letter_draft
      │
f7a5b6c7d8e9  add_tailored_cv_and_match_reason
      │
a8b6c7d8e9f0  add_filtered_out_status
      │
2f488d1e25ad  add_company_website
      │
777c6c8d6179  add_recruiter_contact
      │
b9c8d7e6f5a4  add_applied_at
      │
c0d9e8f7a6b5  add_discarded_status                      (head)
```

| Revision        | Что добавляет | Колонки / значения |
| --------------- | ------------- | ------- |
| `2682ca1c3796`  | Базовая схема: `job_postings` + master-profile (профиль, опыт, навыки) | — |
| `b3f1a2c4d5e6`  | Дедуп сорсинга | `source_job_id` (`String(512)`, nullable, **unique**, index) |
| `d5e3f4a5b6c7`  | Метаданные вакансии | `location`, `employment_type`, `seniority_level`, `salary` (все nullable) |
| `e6f4a5b6c7d8`  | Черновик письма | `cover_letter_draft` (`Text`, nullable) |
| `f7a5b6c7d8e9`  | Tailored CV + обоснование | `tailored_cv_draft` (`Text`), `match_reason` (`Text`) |
| `a8b6c7d8e9f0`  | Статус пре-скрина | значение `FILTERED_OUT` в enum `job_status` |
| `2f488d1e25ad`  | Домен работодателя | `company_website` (`String(255)`) |
| `777c6c8d6179`  | Контакт рекрутёра | `recruiter_name`, `recruiter_email` (`String(255)`) |
| `b9c8d7e6f5a4`  | Отметка отклика | `applied_at` (`DateTime`, nullable) |
| `c0d9e8f7a6b5`  | Статус удаления | значение `DISCARDED` в enum `job_status` |

> **Enum-ревизии (`a8b6c7d8e9f0`, `c0d9e8f7a6b5`)**: на Postgres —
> `ALTER TYPE ... ADD VALUE IF NOT EXISTS` (вне транзакции); на SQLite (dev/test) —
> no-op, т.к. enum хранится как `VARCHAR`. Удаление значения enum не поддерживается
> без пересоздания типа, поэтому такие ревизии намеренно не downgrade-able.

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
