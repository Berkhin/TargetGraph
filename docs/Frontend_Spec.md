# Component Specification: Frontend (React + Vite SPA)

Браузерный SPA для ленты вакансий и запуска AI-сопоставления. Общается с FastAPI
по REST (TanStack Query) и зеркалит бэкенд-контракты 1:1.

## 1. Стек

* **React 19** + **TypeScript** (строго: `type` only — без `interface`/`any`).
* **Vite 8** — дев-сервер на `http://localhost:5173` (см. `CORSSettings`).
* **TanStack Query 5** — серверное состояние (кэш, инвалидация, статусы).
* **axios** — HTTP-клиент (`shared/api/client.ts`).
* **shadcn/ui** (Radix + Tailwind v4) — UI-компоненты; **sonner** — тосты.

## 2. Структура (`frontend/src`)

```
contracts/            # Зеркало backend DTO (single source of truth)
  job.ts              #   Job / JobStatus  ← app/models/schemas/job.py
  profile.ts          #   Profile          ← app/models/schemas/profile.py
  emailVerification.ts
shared/
  api/client.ts       # axios-инстанс (baseURL)
  api/errors.ts       # нормализация ошибок
lib/utils.ts          # cn() и утилиты
components/ui/        # shadcn: badge, button, card, skeleton, sonner
features/
  jobs-board/
    api/              # jobs.service.ts, types.ts (re-export контрактов), queryKeys.ts
    hooks/            # useJobs, useMatchJob
    ui/JobCard.tsx    # карточка вакансии (бейджи метаданных + кнопка match)
  profiles/
    api/profiles.service.ts
    hooks/useActiveProfile.ts
pages/JobsFeedPage.tsx
App.tsx / main.tsx    # корень приложения + провайдеры
```

## 3. Принципы

* **Feature-sliced.** Каждая фича самодостаточна: `api` (сервис + ключи кэша +
  типы) → `hooks` (обёртки TanStack Query) → `ui` (презентационные компоненты).
* **Контракты — единый источник правды.** `contracts/*` повторяют Pydantic-схемы
  бэкенда по именам полей (`job_title`, `company_name`, `match_score`, …).
  `features/*/api/types.ts` ре-экспортирует их под именами схем сервера.
* **Активный профиль.** `useActiveProfile` дёргает `GET /profiles/active`, чтобы
  получить реальный `profile_id` для `POST /jobs/{id}/match` (без хардкода).

## 4. Ключевые потоки данных

* **Лента вакансий:** `JobsFeedPage` → `useJobs` → `GET /jobs?job_status=NEW` →
  список `JobCard`.
* **Запуск матчинга:** кнопка в `JobCard` → `useMatchJob` (mutation) →
  `POST /jobs/{id}/match?profile_id=...` → инвалидация кэша вакансий.
* **Метаданные:** `JobCard` выводит `location` / `employment_type` /
  `seniority_level` / `salary` как `Badge`, если не `null`
  (см. [Job_Metadata_Spec.md](./Job_Metadata_Spec.md)).

## 5. Запуск

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
npm run build    # tsc -b && vite build
```
