# Changelog

Все значимые изменения проекта **TargetGraph**. Формат — обратный хронологический;
технические термины оставлены на английском, чтобы совпадать с кодом и остальной
документацией (`docs/`).

---

## [Unreleased] — Cold Outreach & Parallel Pipeline

Крупная веха: приложение перестало быть «матчер вакансий» и стало end-to-end
инструментом аутрича. Добавлены стриминг прогресса через WebSocket, параллельные
узлы LangGraph, дешёвый пре-скрининг на этапе сорсинга, поиск контактов рекрутёров
через Hunter.io и отправка писем с PDF-вложением через Gmail REST API.

> **Migration chain (Alembic):**
> `f7a5b6c7d8e9` → `a8b6c7d8e9f0` → `2f488d1e25ad` → `777c6c8d6179`
> (см. раздел [3. Изменения в БД](#3-изменения-в-бд)).

---

### 1. Архитектура LangGraph

Пайплайн обработки вакансии — это `StateGraph`, скомпилированный в
`compiled_graph` ([backend/app/ai/orchestrator.py](backend/app/ai/orchestrator.py#L96)).
Состояние строго типизировано через Pydantic-модель `GraphState`
([backend/app/ai/state.py:71](backend/app/ai/state.py#L71)).

#### 1.1. Топология графа

```
                    START
                      │
              extract_requirements
                      │
                 match_profile
                      │
            ┌── should_draft (score gate) ──┐
   score < threshold │              │ score >= threshold
                      │             │
                     END    ┌───────┴────────────────┐
                            │                         │
               find_recruiter_contact      generate_tailored_cv   ◄── ПАРАЛЛЕЛЬНО
                            │                         │
                  generate_cover_letter              │
                            │                         │
                            └──────────┬──────────────┘
                                       │  (fan-in / implicit join)
                                    reviewer
                                       │
                          ┌── should_revise ──┐
            comments && rev<3 │              │ approved || rev==3
                              │             │
                  generate_cover_letter    END
                  (только письмо, max 3)
```

#### 1.2. Параллельные узлы (CV ∥ Hunter)

После `match_profile` роутер `should_draft`
([nodes.py:852](backend/app/ai/nodes.py#L852)) при `match_score >= score_threshold`
возвращает **список** имён узлов — это и есть сигнал LangGraph на параллельный
fan-out:

```python
# should_draft(): список → две ветки стартуют одновременно
return ["find_recruiter_contact", "generate_tailored_cv"]
# ниже порога — короткое замыкание в END
return "__end__"
```

Стартуют две независимые ветки:

| Ветка | Узлы | Пишет в state | Модель / темп. |
| --- | --- | --- | --- |
| **CV** | `generate_tailored_cv` | `tailored_cv` | Gemini pro, low temp (без галлюцинаций) |
| **Cover Letter** | `find_recruiter_contact` → `generate_cover_letter` | `recruiter_name`, `recruiter_email`, `cover_letter_draft` | Hunter API (без LLM), затем Gemini pro, high temp |

Ветки сходятся (fan-in) на узле `reviewer` — обе входящие рёбра ведут в него
([orchestrator.py:83-84](backend/app/ai/orchestrator.py#L83)), и LangGraph
неявно ждёт завершения обеих.

**Почему не нужен reducer:** ветки пишут в **непересекающиеся** ключи стейта
(`tailored_cv` против `cover_letter_draft`/`recruiter_*`), поэтому merge их
результатов происходит автоматически, кастомный reducer не требуется.

#### 1.3. Цикл ревизии

`reviewer` ([nodes.py:771](backend/app/ai/nodes.py#L771)) — строгий fact-check
(только проверка на выдуманный опыт/навыки, не стиль). Роутер `should_revise`
([nodes.py:872](backend/app/ai/nodes.py#L872)) зацикливает **только**
`generate_cover_letter`:

* `review_comments` непусто **и** `revision_number < 3` → назад в `generate_cover_letter`;
* иначе → `END`.

CV генерируется один раз и переиспользуется; Hunter-lookup в цикле не повторяется.
Счётчик `revision_number` ограничен 3 — защита от бесконечного цикла.

#### 1.4. GraphState — ключевые поля

| Поле | Тип | Источник | Назначение |
| --- | --- | --- | --- |
| `job_text`, `profile_text` | `str` | input | Сырьё для всех узлов |
| `company_website` | `str \| None` | input (Apify) | Домен работодателя для Hunter |
| `source_url` | `str` | input | URL вакансии; парсится в домен, если не job-board |
| `company_name` | `str` | input | Fallback для Hunter |
| `score_threshold` | `int = 50` | input | Порог гейта `should_draft` |
| `match_score` | `int` | `match_profile` | 0–100 |
| `recruiter_name` / `recruiter_email` | `str \| None` | `find_recruiter_contact` | Контакт рекрутёра (может быть `None`) |
| `cover_letter_draft` | `str \| None` | `generate_cover_letter` | Текст письма |
| `tailored_cv` | `str \| None` | `generate_tailored_cv` | ATS-резюме (Markdown) |
| `review_comments` | `list[str]` | `reviewer` | Пусто = одобрено |
| `revision_number` | `int` | `reviewer` | Cap = 3 |
| `drafting_failed` | `bool` | draft-узлы | Флаг ошибки LLM → стоп цикла, не сохранять брак |
| `analysis_failed` | `bool` | analysis-узлы | Флаг ошибки → не сохранять ложный REJECTED |

#### 1.5. Fail-soft: контакты не найдены

Узел `find_recruiter_contact` ([nodes.py:554](backend/app/ai/nodes.py#L554))
**никогда не роняет граф**. Любой провал деградирует в «контакт не найден»:

```python
# нет ни домена, ни имени компании
if not domain and not company:
    return {"recruiter_name": None, "recruiter_email": None}

try:
    contacts = await HunterClient().search_hiring_managers(domain, company=company)
except Exception:  # noqa: BLE001 — узел не должен крашить граф
    logger.exception("find_recruiter_contact.failed")
    return {"recruiter_name": None, "recruiter_email": None}

if not contacts:
    return {"recruiter_name": None, "recruiter_email": None}
```

Граф всегда продолжает в `generate_cover_letter`. Узел письма проверяет наличие
имени и подставляет fallback-обращение:

* есть `recruiter_name` → персональное обращение по имени;
* `None` → системный промпт даёт generic-приветствие **«Dear Hiring Team,»**.

`recruiter_name`/`recruiter_email` сохраняются в БД как `None` — это **не ошибка**;
вакансия всё равно доходит до MATCHED/REJECTED по score.

#### 1.6. Стриминг через WebSocket

* **Endpoint:** `WS /api/v1/jobs/{job_id}/ws-match?profile_id=<uuid>`
  ([jobs.py:245](backend/app/api/v1/jobs.py#L245)).
* **Драйвер:** `run_pipeline_stream(...)`
  ([services/orchestrator.py:285](backend/app/services/orchestrator.py#L285))
  использует `compiled_graph.astream_events(..., version="v2")` и отправляет фрейм
  на каждое `on_chain_end` отслеживаемого узла (`_PIPELINE_NODES`).

Последовательность фреймов:

```jsonc
{"step": "init", "message": "Данные загружены"}
{"step": "extract_requirements", "message": "Шаг '…' завершён"}
{"step": "match_profile", "score": 72, "reason": "…"}
{"step": "find_recruiter_contact", "recruiter_name": "…", "recruiter_email": "…"}
{"step": "generate_cover_letter", "message": "…"}
{"step": "generate_tailored_cv", "message": "…"}
{"step": "reviewer", "message": "…"}
{"step": "done", "status": "MATCHED", "score": 72, "reason": "…",
 "cover_letter_draft": "…", "tailored_cv_draft": "…"}
```

Параллельная задача `_watch_disconnect()` ловит закрытие вкладки клиентом и
останавливает граф, чтобы не жечь LLM-вызовы; при дисконнекте результат в БД
не сохраняется. Ошибки (`analysis_failed`, `drafting_failed`,
`PipelineExecutionError`) отдаются фреймом `{"step": "error", "message": "…"}`.

---

### 2. Пайплайн Холодного Аутрича

#### 2.1. Hunter.io — поиск людей по `company_website`

* **Клиент:** `HunterClient`
  ([backend/app/services/hunter_client.py:42](backend/app/services/hunter_client.py#L42)).
* **Endpoint:** Hunter v2 `domain-search` — `https://api.hunter.io/v2/domain-search`.
* **Auth:** API-ключ как query-параметр `api_key` (env `HUNTER_API_KEY`).
* **Метод:** `search_hiring_managers(domain, *, company=None, department="hr", limit=10)`.

Выбор идентификатора компании (по убыванию точности):

1. `company_website` (Apify `companyWebsite`) → домен напрямую — самый надёжный;
2. `source_url` → домен через `_employer_domain_from_url()`
   ([nodes.py:404](backend/app/ai/nodes.py#L404)), **но** хосты job-board'ов
   отбрасываются (`_NON_EMPLOYER_HOSTS`: `linkedin.com`, `indeed.com`,
   `glassdoor.com`, `lever.co`, `greenhouse.io`, `workable.com`,
   `smartrecruiters.com`, `bamboohr.com` и др. — [nodes.py:40](backend/app/ai/nodes.py#L40));
3. `company_name` → Hunter резолвит домен на своей стороне.

#### 2.2. Фильтрация generic-ящиков

Hunter тегирует каждую запись как `type: "personal"` (именованный человек) или
`type: "generic"` (ролевой ящик — `careers@`, `jobs@`, `info@`). TargetGraph
держит **строгий гейт** `_is_personal_named()`
([hunter_client.py:178](backend/app/services/hunter_client.py#L178)):

```python
@staticmethod
def _is_personal_named(record: dict) -> bool:
    first_name = (record.get("first_name") or "").strip()
    return record.get("type") == "personal" and bool(first_name)
```

То есть запись проходит, только если `type == "personal"` **и** есть непустое
`first_name` — иначе персональное обращение в письме невозможно. Каждая
прошедшая запись маппится в DTO `HunterContact`
([schemas/hunter.py:15](backend/app/models/schemas/hunter.py#L15)):
`email`, `first_name`, `last_name`, `position`, `linkedin_url`, `confidence` (0–100).

> **Fail-soft by design:** любая ошибка (сеть, неверный ключ, исчерпанные
> кредиты) логируется и деградирует в пустой список — см. §1.5.

#### 2.3. Gmail Client — OAuth 2.0 и MIME

* **Клиент:** `GmailClient`
  ([backend/app/services/gmail_client.py:55](backend/app/services/gmail_client.py#L55)).
* **Scope:** `https://www.googleapis.com/auth/gmail.send` (только отправка,
  least-privilege).
* **Файлы:** `credentials.json` (OAuth client secrets, тип «Desktop App») и
  `token.json` (кэш токена) — оба git-ignored, пути настраиваются через
  `GMAIL_CREDENTIALS_FILE` / `GMAIL_TOKEN_FILE`
  ([config.py GmailSettings](backend/app/core/config.py#L427)).

**OAuth-флоу** `_authenticate()`
([gmail_client.py:74](backend/app/services/gmail_client.py#L74)):

1. загрузить `token.json` (`Credentials.from_authorized_user_file`);
2. валиден → используем сразу;
3. истёк, но есть `refresh_token` → `creds.refresh(Request())` (на `RefreshError`
   — сброс и повторный консент; в Testing-режиме токены живут ~7 дней);
4. нет валидного токена → `InstalledAppFlow.from_client_secrets_file(...)` +
   `flow.run_local_server(port=0)` (свободный loopback-порт, браузерный консент);
5. атомарная запись токена (temp-файл + rename).

**Сборка MIME с PDF** `_send_sync()`
([gmail_client.py:129](backend/app/services/gmail_client.py#L129)):

```python
message = EmailMessage()
message["To"] = to_email
message["Subject"] = subject
message.set_content(body_text)                 # plain-text body

if attachment_bytes:                           # PDF/любой файл
    maintype, _, subtype = _guess_mimetype(attachment_filename).partition("/")
    message.add_attachment(
        attachment_bytes, maintype=maintype, subtype=subtype,
        filename=attachment_filename or "attachment",
    )

encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
return service.users().messages().send(
    userId="me", body={"raw": encoded_message}
).execute()
```

Детали: блокирующие вызовы Google API уводятся в worker-тред
(`asyncio.to_thread`), отправка сериализуется `asyncio.Lock` (защита от гонок при
записи `token.json` и первичном консенте). MIME кодируется в **base64url** целиком
(headers + body + attachment) и уходит методом `users.messages.send`.

#### 2.4. REST-эндпоинты

| Метод / путь | Функция | Что делает |
| --- | --- | --- |
| `POST /api/v1/jobs/{job_id}/match?profile_id=…` | `match_job()` ([jobs.py:89](backend/app/api/v1/jobs.py#L89)) | Полный пайплайн (включая Hunter-lookup), синхронно |
| `WS /api/v1/jobs/{job_id}/ws-match?profile_id=…` | `match_job_ws()` ([jobs.py:245](backend/app/api/v1/jobs.py#L245)) | Тот же пайплайн со стримингом прогресса |
| `POST /api/v1/jobs/{job_id}/outreach/send` | `send_outreach_email()` ([jobs.py:174](backend/app/api/v1/jobs.py#L174)) | Отправка письма с PDF через Gmail |

**Request `OutreachSendRequest`** ([schemas/outreach.py:13](backend/app/models/schemas/outreach.py#L13)):

```python
class OutreachSendRequest(BaseModel):
    to_email: EmailStr
    subject: str                              # 1..998 (RFC 5322 cap)
    body: str                                 # min_length 1
    attachment_filename: str | None = None    # напр. "cv.pdf"
    attachment_content_base64: str | None = None  # base64 байтов файла
```

Сервер декодирует вложение `base64.b64decode(..., validate=True)` (битый base64 →
400), вызывает `gmail.send_email(...)`. **Response `OutreachSendResponse`**:

```json
{"status": "sent", "message_id": "abc-123xyz", "to_email": "recruiter@acme.com"}
```

Ошибки Gmail (`HttpError`) и прочие (нет credentials, провал OAuth) → 500.

---

### 3. Изменения в БД

#### 3.1. Новые поля (`job_postings`)

| Поле | Тип | Null | Назначение |
| --- | --- | --- | --- |
| `company_website` | `String(255)` | ✓ | Реальный домен работодателя из Apify (`companyWebsite`), отдельно от `source_url` (всегда LinkedIn). Используется для точного Hunter-lookup. [job_posting.py:39](backend/app/models/sql/job_posting.py#L39) |
| `tailored_cv_draft` | `Text` | ✓ | ATS-оптимизированное резюме (Markdown) из узла `generate_tailored_cv`. [job_posting.py:68](backend/app/models/sql/job_posting.py#L68) |
| `match_reason` | `Text` | ✓ | Обоснование score (добавлено в той же миграции, что и `tailored_cv_draft`) |
| `recruiter_name` | `String(255)` | ✓ | Контакт из Hunter (см. §2) |
| `recruiter_email` | `String(255)` | ✓ | Email контакта из Hunter |

> В `GraphState` поле называется `tailored_cv`, в БД и в `done`-фрейме —
> `tailored_cv_draft`. Это разные слои (runtime-state vs persisted column).

#### 3.2. Новый статус `FILTERED_OUT`

`JobStatus` ([backend/app/models/enums.py:12](backend/app/models/enums.py#L12))
теперь имеет 4 значения:

```python
class JobStatus(str, enum.Enum):
    NEW = "NEW"
    MATCHED = "MATCHED"
    REJECTED_BY_AI = "REJECTED_BY_AI"
    FILTERED_OUT = "FILTERED_OUT"   # отсеяно дешёвым пре-скрином на сорсинге
```

**`FILTERED_OUT`** — вакансия отброшена дешёвым relevance-гейтом на этапе
сорсинга (до полного пайплайна). Не показывается на доске и **не пере-скрейпится**,
но сохраняется в БД, чтобы дедуп по `source_job_id` узнавал её на будущих прогонах.

**Где присваивается** — `sourcing_task.py:182`
([backend/app/tasks/sourcing_task.py:182](backend/app/tasks/sourcing_task.py#L182)):

```python
relevance = await evaluate_job_relevance(job_create.description, profile_text)
score = relevance["score"]
if score is not None and score < _PRESCREEN_THRESHOLD:   # _PRESCREEN_THRESHOLD = 55
    status = JobStatus.FILTERED_OUT
else:
    # score >= порога ИЛИ None (пре-скрин недоступен): fail-open → NEW
    status = JobStatus.NEW
```

Логика пре-скрина:

1. сорсинг (Apify) → дедуп по `source_job_id` (известные не пере-скорятся);
2. для **новых** постингов — дешёвый LLM-гейт `evaluate_job_relevance()`
   ([nodes.py:890](backend/app/ai/nodes.py#L890)), грубая релевантность, не
   квалификация;
3. `score < 55` → `FILTERED_OUT`; иначе `NEW`;
4. **fail-open:** ошибка LLM / пустой score → `NEW`, чтобы сбой Gemini не отсеивал
   молча все вакансии — пусть решает полный пайплайн позже.

#### 3.3. Alembic-миграции

| Revision | Файл | Что добавляет |
| --- | --- | --- |
| `f7a5b6c7d8e9` | `..._add_tailored_cv_and_match_reason.py` | `tailored_cv_draft` (Text), `match_reason` (Text) |
| `a8b6c7d8e9f0` | `..._add_filtered_out_status.py` | значение `FILTERED_OUT` в enum `job_status` |
| `2f488d1e25ad` | `..._add_company_website.py` | `company_website` (String 255) |
| `777c6c8d6179` | `..._add_recruiter_contact.py` | `recruiter_name`, `recruiter_email` (String 255) |

Замечание по `a8b6c7d8e9f0`: на Postgres — `ALTER TYPE ... ADD VALUE IF NOT EXISTS
'FILTERED_OUT'` (вне транзакции); на SQLite (dev/test) — no-op, т.к. enum хранится
как `VARCHAR`. Миграция намеренно **не downgrade-able**: Postgres не умеет удалять
одно значение enum без пересоздания типа.

---

## Предыдущие версии

Базовая схема, дедуп сорсинга (`source_job_id`), метаданные вакансии и черновик
письма (`cover_letter_draft`) — см. историю в [docs/Migrations.md](docs/Migrations.md)
(цепочка `2682ca1c3796` → … → `e6f4a5b6c7d8`).
