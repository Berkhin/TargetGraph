import { apiClient } from "@/shared/api/client";
import type { JobRead, JobStatus } from "./types";

// GET /jobs?job_status={status} — list postings filtered by lifecycle status.
// NOTE: the backend query param is `job_status` (see app/api/v1/jobs.py),
// not `status`.
export async function getJobsByStatus(status: JobStatus): Promise<JobRead[]> {
  const { data } = await apiClient.get<JobRead[]>("/jobs", {
    params: { job_status: status },
  });
  return data;
}

// Sourced postings awaiting AI matching.
export async function getNewJobs(): Promise<JobRead[]> {
  return getJobsByStatus("NEW");
}

// Postings the AI pipeline matched — they carry a cover_letter_draft.
export async function getMatchedJobs(): Promise<JobRead[]> {
  return getJobsByStatus("MATCHED");
}
