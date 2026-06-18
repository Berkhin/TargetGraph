// DTOs for the jobs-board feature, mirroring the FastAPI backend.
// Single source of truth lives in @/contracts/job (mirrors
// backend/app/models/schemas/job.py); we re-export under the backend's
// schema names so the API layer reads 1:1 with the server.
// Project convention: `type` only — no `interface`, no `any`.

import type { Job, JobStatus } from "@/contracts/job";

export type { JobStatus };

// Mirrors JobRead. NOTE: real field names are `job_title` / `company_name` /
// `match_score` / `cover_letter_draft` (not title/company/score/cover_letter).
export type JobRead = Job;

// Mirrors JobMatchResponse — backend extends JobRead with the post-pipeline
// state (match_score, cover_letter_draft, status all populated).
export type JobMatchResponse = JobRead;
