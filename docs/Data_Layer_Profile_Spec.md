# Component Specification: Master Profile Data Layer

## 1. Архитектурный подход
Расширение текущего Data Layer (SQLAlchemy 2.0 + asyncpg) для хранения профиля кандидата. 
Используется паттерн Repository для инкапсуляции.

## 2. Модели БД (SQLAlchemy)
Связь One-to-Many между профилем и его сущностями.

* **`master_profiles`**
  * `id` (UUID, PK)
  * `candidate_name` (String)
  * `target_titles` (JSONB / ARRAY)
  * `preferences` (JSONB)
* **`profile_experiences`**
  * `id` (UUID, PK)
  * `profile_id` (UUID, FK -> master_profiles.id)
  * `company` (String)
  * `role` (String)
  * `highlights` (JSONB / ARRAY) - список достижений
  * `start_date` (Date)
  * `end_date` (Date, nullable)
* **`profile_skills`**
  * `id` (UUID, PK)
  * `profile_id` (UUID, FK -> master_profiles.id)
  * `category` (String)
  * `skills` (JSONB / ARRAY)

## 3. Репозиторий
* `ProfileRepository.get_full_profile(profile_id)` — достает профиль со всеми связанными `experiences` и `skills` (используя `selectinload` для асинхронной подгрузки) и отдает в виде единой вложенной Pydantic-модели.