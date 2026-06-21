# Component Specification: Real-time Matching (WebSocket)

Стриминг AI-пайплайна сопоставления вакансии с профилем по WebSocket — узел за
узлом, чтобы пользователь видел прогресс, а не ждал ~30 c единственного вердикта.
Это потоковый «двойник» REST-эндпоинта `POST /jobs/{id}/match`.

## 1. Endpoint

```
WS /api/v1/jobs/{job_id}/ws-match?profile_id=<UUID>
```

* **Файл:** `app/api/v1/jobs.py` → `match_job_ws`.
* Роут владеет только `websocket.accept()`; всё остальное (кадры, закрытие,
  обработка дисконнекта) — в `run_pipeline_stream`
  (`app/services/orchestrator.py`).
* В отличие от REST-роутов **не** зависит от `get_session`: стриминговый сервис
  сам владеет короткоживущими сессиями.

## 2. Протокол кадров (Server → Client, JSON)

| `step`          | Поля                                         | Когда |
| --------------- | -------------------------------------------- | ----- |
| `init`          | `message`                                    | входные данные загружены |
| `match_profile` | `score`, `reason`                            | сразу после узла оценки (с причиной!) |
| `find_recruiter_contact` | `recruiter_name`, `recruiter_email`  | контакт найден (или `None`) |
| `<node>`        | `message`                                    | завершение `extract_requirements` / `generate_tailored_cv` / `generate_cover_letter` / `reviewer` |
| `done`          | `status`, `score`, `reason`, `cover_letter_draft`, `tailored_cv_draft` | финал, затем сокет закрывается |
| `error`         | `message`                                    | вакансия/профиль не найдены, ошибка пайплайна или сохранения |

Узлы пайплайна, чьи границы форвардятся (`_PIPELINE_NODES`): `extract_requirements`,
`match_profile`, `find_recruiter_contact`, `generate_tailored_cv`,
`generate_cover_letter`, `reviewer` (фильтр по `on_chain_end` в `astream_events`
v2). Параллельные ветки CV ∥ контакт стримятся по мере завершения каждого узла;
порядок их кадров не детерминирован.

## 3. Дисциплина соединений

Пайплайн LangGraph DB-agnostic, поэтому БД-соединение **не** держится во время
(долгого) прогона графа:

1. **Короткая read-сессия** — читает job + profile, затем отпускает соединение.
2. **Прогон графа без соединения** — `astream_events`, слияние частичных
   выходов узлов в `final_state` (last-write-wins, корректно для повторного
   `generate_cover_letter` в цикле ревизий).
3. **Короткая write-сессия** — отдельная атомарная единица работы: сохранение
   результата + `commit`.

Это не даёт «брошенным» стримам выесть весь пул соединений (тот же паттерн, что
в `run_sourcing_job`).

## 4. Обработка дисконнекта

`send`-only хендлер не замечает закрытую вкладку надёжно. Параллельная задача
`_watch_disconnect` блокируется на `websocket.receive()` (единственный канал, по
которому Starlette доставляет `websocket.disconnect`). При обрыве: цикл графа
останавливается на ближайшей границе узла, LLM-вызовы прекращаются, результат не
сохраняется, сервер не падает.

Все исходящие операции — best-effort (`_safe_send` / `_safe_close` /
`_safe_error`): на мёртвом сокете `send_json` может бросить не только
`WebSocketDisconnect`, поэтому ловится широко по дизайну.

## 5. Тесты

`tests/test_jobs_ws.py` — happy-path стрим, ранний выход при отсутствии
job/profile, поведение при дисконнекте.
