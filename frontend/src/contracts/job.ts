// Strict API contract for the Job Posting entity.
// Mirrors backend/app/models/schemas/job.py (JobRead) and app/models/enums.py.
// Project convention: `type` only — no `interface`, no `any`.

// Mirrors app.models.enums.JobStatus.
export type JobStatus = "NEW" | "MATCHED" | "REJECTED_BY_AI";

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
  cover_letter_draft: string | null;
  source_job_id: string | null;
  // Rich metadata from the LinkedIn jobs scraper; any may be null.
  location: string | null;
  employment_type: string | null;
  seniority_level: string | null;
  salary: string | null;
  created_at: string;
  updated_at: string;
};
