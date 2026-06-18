// Strict API contract for the Job Posting entity.
// Mirrors backend/app/models/schemas/job.py (JobRead) and app/models/enums.py.
// Project convention: `type` only — no `interface`, no `any`.

// Mirrors app.models.enums.JobStatus.
export type JobStatus =
  | "NEW"
  | "MATCHED"
  | "REJECTED_BY_AI"
  | "FILTERED_OUT"
  // Soft-deleted by the user; hidden from every board, kept for sourcing dedup.
  | "DISCARDED";

// GET /api/v1/jobs — mirrors JobRead.
// UUIDs and datetimes arrive as ISO strings over the wire.
export type Job = {
  id: string;
  company_name: string;
  job_title: string;
  description: string;
  source_url: string;
  status: JobStatus;
  match_score: number | null;
  match_reason: string | null;
  cover_letter_draft: string | null;
  tailored_cv_draft: string | null;
  source_job_id: string | null;
  // Rich metadata from the LinkedIn jobs scraper; any may be null.
  location: string | null;
  employment_type: string | null;
  seniority_level: string | null;
  salary: string | null;
  // Cold-outreach contact resolved during matching (Hunter.io); null if none.
  recruiter_name: string | null;
  recruiter_email: string | null;
  // ISO timestamp of a successful recruiter outreach send; null until applied.
  applied_at: string | null;
  created_at: string;
  updated_at: string;
};
