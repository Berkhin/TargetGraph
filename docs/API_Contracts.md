# API Contracts & Communication Protocols

> Live interactive schema (OpenAPI/Swagger) is auto-served at **`/docs`** and
> **`/redoc`** by FastAPI — that is the source of truth for request/response shapes.
> This document is a curated map of endpoints, clearly separating **implemented**
> from **planned**.

## 1. REST API — Jobs (✅ implemented)

Router prefix `/api/v1/jobs` ([backend/app/api/v1/jobs.py](../backend/app/api/v1/jobs.py)).

| Method & path | Function | Purpose |
| --- | --- | --- |
| `POST /api/v1/jobs` | `create_job` | add a posting (raw text / link) |
| `GET /api/v1/jobs` | `list_jobs` | list with `job_status` filter |
| `GET /api/v1/jobs/{job_id}` | `get_job` | fetch one |
| `PATCH /api/v1/jobs/{job_id}` | `update_job_status_and_score` | update status / score |
| `DELETE /api/v1/jobs/{job_id}` | `delete_job` | **soft-delete** → status `DISCARDED` (204) |
| `POST /api/v1/jobs/{job_id}/match?profile_id=…` | `match_job` | run full pipeline synchronously |
| `POST /api/v1/jobs/{job_id}/outreach/send` | `send_outreach_email` | send email + PDF via Gmail; stamps `applied_at` |
| `WS /api/v1/jobs/{job_id}/ws-match?profile_id=…` | `match_job_ws` | streaming pipeline (see §3) |

**`POST /{job_id}/match`** — query param `profile_id: UUID`. Returns the updated
job (`match_score`, `match_reason`, `cover_letter_draft`, `tailored_cv_draft`,
`recruiter_name`, `recruiter_email`, `status`). Status is `MATCHED` if
`score >= score_threshold` (default **50**), else `REJECTED_BY_AI`. Unknown
job/profile → `404`. Examples: [EXAMPLES_JOB_MATCHING.md](./EXAMPLES_JOB_MATCHING.md).

**`POST /{job_id}/outreach/send`** — body `OutreachSendRequest`
(`to_email`, `subject`, `body`, optional `attachment_filename`,
`attachment_content_base64`). The PDF is generated **client-side** (jsPDF) and
uploaded base64. Returns `OutreachSendResponse`
(`{"status": "sent", "message_id": "...", "to_email": "..."}`). Gmail errors → `500`.

## 2. REST API — Profiles & Contacts (✅ implemented)

| Method & path | Purpose |
| --- | --- |
| `GET /api/v1/profiles` | list candidate profiles (with experience & skills) |
| `GET /api/v1/profiles/active` | active profile (deterministically first; `404` if none) — frontend uses it to get a real `profile_id` for `/jobs/{id}/match` |
| `POST /api/v1/contacts/verify-email` | **standalone** SMTP/MX/permutation email verifier — *not* part of the matching pipeline ([Email_Verification_Spec.md](./Email_Verification_Spec.md)) |

## 3. WebSocket API — real-time matching (✅ implemented)

```
ws://localhost:8000/api/v1/jobs/{job_id}/ws-match?profile_id=<UUID>
```

Streams the matching pipeline node-by-node (`init` → `match_profile` with
`score`/`reason` → per-node frames → `done` / `error`). Full frame protocol:
[Realtime_Matching_Spec.md](./Realtime_Matching_Spec.md).

## 4. Planned / not yet implemented (⏳)

These are design targets, **not** in the codebase today. Do not assume they exist.

* **`ws://…/ws/pipeline-status`** — a general background-task status stream
  (target `PipelineEvent` contract below).
* **`POST /api/v1/webhooks/gmail`** — Gmail inbox parsing via Google Cloud Pub/Sub
  (push notifications → LLM classification of replies). *Gmail is currently
  outbound-only; no webhook or Pub/Sub integration is implemented.*
* **`POST /api/v1/applications/{job_id}/generate` / `/send`** — a separate
  application-tracking resource. Today, outreach is `POST /jobs/{id}/outreach/send`
  and "applied" state is the `applied_at` timestamp on `job_postings`.

### Target `PipelineEvent` type (frontend, planned)

```typescript
// Strict type definitions (No interfaces)
export type PipelineStage =
  | "Sourcing"
  | "Matching"
  | "Email_Discovery"
  | "Document_Generation"
  | "Completed"
  | "Failed";

export type PipelineEvent = {
  jobId: string;
  stage: PipelineStage;
  progress: number;   // 0-100
  message: string;
  timestamp: string;  // ISO 8601
  payload?: Record<string, unknown>;
};
```
