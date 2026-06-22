# Data Models & Database Schema

> Ground truth: the SQLAlchemy models in
> [backend/app/models/sql/](../backend/app/models/sql/) and the Alembic chain
> ([Migrations.md](./Migrations.md)). PostgreSQL in prod; SQLite in dev/test.

## 1. Conventions
* Primary keys are `id` (UUID).
* Timestamps: `created_at`, `updated_at` (auto-updated).
* Frontend contracts (TypeScript) use `type` exclusively (mirror these models 1:1).

## 2. Tables

There are **four** tables. Recruiter contact info is stored **as columns on
`job_postings`** — there are **no** separate `contacts` or `applications` tables.

### `job_postings` ([job_posting.py](../backend/app/models/sql/job_posting.py))
| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID (PK) | |
| `company_name` | String(255) | |
| `job_title` | String(255) | |
| `description` | Text | |
| `source_url` | String | usually the LinkedIn URL |
| `source_job_id` | String(512), nullable, **unique**, index | sourcing dedup key |
| `company_website` | String(255), nullable | real employer domain (Apify) — used for Hunter |
| `location` / `employment_type` / `seniority_level` / `salary` | String, nullable | scraper metadata ([Job_Metadata_Spec.md](./Job_Metadata_Spec.md)) |
| `employee_count` | Integer, nullable | company headcount (Apify `companyEmployeesCount`, requires `scrapeCompany`) |
| `company_linkedin_url` | String(512), nullable | company LinkedIn page (Apify `companyLinkedinUrl`, requires `scrapeCompany`) |
| `match_score` | Integer, nullable | 0–100 |
| `match_reason` | Text, nullable | score justification |
| `cover_letter_draft` | Text, nullable | generated letter |
| `tailored_cv_draft` | Text, nullable | ATS CV (Markdown) — runtime state calls it `tailored_cv` |
| `recruiter_name` | String(255), nullable | Hunter.io contact |
| `recruiter_email` | String(255), nullable | Hunter.io contact |
| `status` | Enum `JobStatus` | see below |
| `applied_at` | DateTime, nullable | set when an outreach email is sent |
| `created_at` / `updated_at` | DateTime | |

### `master_profiles` ([profile.py](../backend/app/models/sql/profile.py))
`id` (UUID) · `candidate_name` (String) · `target_titles` (Array) ·
`preferences` (JSONB) · one-to-many → `profile_experiences`, `profile_skills`.

### `profile_experiences`
`id` · `profile_id` (FK) · `company` · `role` · `highlights` (Array) ·
`start_date` · `end_date` (nullable).

### `profile_skills`
`id` · `profile_id` (FK) · `category` · `skills` (Array).

## 3. `JobStatus` enum ([enums.py](../backend/app/models/enums.py))

| Value | Meaning |
| --- | --- |
| `NEW` | sourced and passed pre-screen; ready for matching |
| `MATCHED` | `match_score >= score_threshold` |
| `REJECTED_BY_AI` | scored below threshold by the full pipeline |
| `FILTERED_OUT` | dropped by the cheap sourcing pre-screen (`< 55`); hidden, kept for dedup |
| `DISCARDED` | user-deleted (soft delete) |

## 4. Access layer
SQLAlchemy 2.0 async + repository pattern (`JobRepository`, `ProfileRepository`).
Repositories accept/return Pydantic DTOs and encapsulate ORM objects; the **request**
owns the transaction (services only `flush`). See
[Data_Layer_Spec.md](./Data_Layer_Spec.md) and
[Data_Layer_Profile_Spec.md](./Data_Layer_Profile_Spec.md).
