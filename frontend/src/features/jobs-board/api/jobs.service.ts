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

// Payload + result for POST /jobs/{id}/outreach/send (mirrors the backend
// OutreachSendRequest / OutreachSendResponse).
export type OutreachSendRequest = {
  to_email: string;
  subject: string;
  body: string;
  // Optional attachment (e.g. the tailored-CV PDF), base64-encoded bytes.
  attachment_filename?: string | null;
  attachment_content_base64?: string | null;
};

export type OutreachSendResponse = {
  status: string;
  message_id: string | null;
  to_email: string;
};

// Send a cold-outreach email for a posting via the Gmail API (backend OAuth).
export async function sendOutreachEmail(
  jobId: string,
  payload: OutreachSendRequest,
): Promise<OutreachSendResponse> {
  const { data } = await apiClient.post<OutreachSendResponse>(
    `/jobs/${jobId}/outreach/send`,
    payload,
  );
  return data;
}
