# Data Models & Database Schema (PostgreSQL)

## 1. Конвенции
* Все таблицы используют `id` (UUID) как Primary Key.
* Timestamps: `created_at`, `updated_at` (с автообновлением).
* Контракты фронтенда (TypeScript) используют исключительно `type`.

## 2. Основные Таблицы

### `master_profiles`
* `id` (UUID)
* `candidate_name` (String)
* `target_titles` (Array of Strings)
* `preferences` (JSONB)

### `profile_experiences`
* `id` (UUID)
* `profile_id` (UUID, Foreign Key)
* `company` (String)
* `role` (String)
* `highlights` (Array of Strings)
* `start_date` (Date)
* `end_date` (Date, nullable)

### `profile_skills`
* `id` (UUID)
* `profile_id` (UUID, Foreign Key)
* `category` (String)
* `skills` (Array of Strings)

### `job_postings`
* `id` (UUID)
* `company_name` (String)
* `job_title` (String)
* `description` (Text)
* `source_url` (String)
* `match_score` (Integer, nullable)
* `status` (Enum) - `NEW`, `MATCHED`, `REJECTED_BY_AI`

### `contacts`
* `id` (UUID)
* `job_posting_id` (UUID, Foreign Key)
* `name` (String, nullable)
* `email` (String, nullable)
* `linkedin_url` (String, nullable)

### `applications`
* `id` (UUID)
* `job_posting_id` (UUID, Foreign Key)
* `contact_id` (UUID, Foreign Key, nullable)
* `status` (Enum) - `PENDING_GENERATION`, `READY_TO_SEND`, `SENT`, `REPLIED`, `INTERVIEW`, `REJECTED`
* `delivery_method` (Enum) - `EMAIL`, `LINKEDIN`
* `generated_resume_url` (String)
* `generated_cover_letter` (Text)