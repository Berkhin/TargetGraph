# Component Specification: Frontend (React + Vite SPA)

Браузерный SPA для ленты вакансий и запуска AI-сопоставления. Общается с FastAPI
по REST (TanStack Query) и зеркалит бэкенд-контракты 1:1.

## 1. Стек

* **React 19** + **TypeScript** (строго: `type` only — без `interface`/`any`).
* **Vite** — дев-сервер на `http://localhost:5173` (см. `CORSSettings`).
* **TanStack Query 5** — серверное состояние (кэш, инвалидация, статусы).
* **React Router** — маршрутизация; **React Hook Form** — формы.
* **axios** — HTTP-клиент (`shared/api/client.ts`).
* **shadcn/ui** (Radix + Tailwind v4) — UI-компоненты; **sonner** — тосты;
  **lucide-react** — иконки.
* **jsPDF** — клиентский рендер Markdown-CV в PDF (динамический импорт).

## 2. Структура (`frontend/src`)

```
contracts/            # Зеркало backend DTO (single source of truth)
  job.ts              #   Job / JobStatus  ← app/models/schemas/job.py
  profile.ts          #   Profile          ← app/models/schemas/profile.py
  emailVerification.ts
shared/
  api/client.ts       # axios-инстанс (baseURL)
  api/errors.ts       # нормализация ошибок
  query keys          # ключи кэша TanStack Query
lib/utils.ts          # cn() и утилиты
components/ui/        # shadcn: badge, button, card, skeleton, dialog, tabs,
                      #   input, label, textarea, sonner
features/
  jobs-board/
    api/              # jobs.service.ts, types.ts (re-export контрактов), queryKeys.ts
    hooks/            # useJobs, useMatchJob, useMatchJobStream (WebSocket), delete/applied
    ui/JobCard.tsx    # карточка вакансии (бейджи метаданных + действия)
  profiles/
    api/profiles.service.ts
    hooks/useActiveProfile.ts
  cover-letters/
    lib/cvToPdf.ts    # Markdown CV → PDF (jsPDF), затем base64 в outreach/send
    ui/               # просмотр/правка письма и CV, отправка рекрутёру
pages/                # JobsFeedPage, ProfilePage, CoverLettersPage
App.tsx / main.tsx    # роутер + провайдеры (QueryClient, Toaster)
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
* **Запуск матчинга (стриминг):** кнопка в `JobCard` → `useMatchJobStream`
  открывает `WS /jobs/{id}/ws-match?profile_id=...`, показывает прогресс по узлам
  (терминал-лог), по `done` инвалидирует кэш вакансий. Синхронный REST-вариант
  `POST /jobs/{id}/match` — через `useMatchJob`.
* **Аутрич:** `cover-letters` рендерит CV → PDF (`cvToPdf.ts`, jsPDF) и шлёт
  `POST /jobs/{id}/outreach/send` (вложение base64). Успех → бэкенд ставит
  `applied_at`.
* **Удаление карточки:** soft-delete через `DELETE /jobs/{id}` (статус
  `DISCARDED`), затем инвалидация кэша.
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
