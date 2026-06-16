import { apiClient } from "@/shared/api/client";
import type { JobMatchResponse, JobRead } from "./types";

// GET /jobs?job_status=NEW
// NOTE: the backend query param is `job_status` (see app/api/v1/jobs.py),
// not `status`.
export async function getNewJobs(): Promise<JobRead[]> {
  const { data } = await apiClient.get<JobRead[]>("/jobs", {
    params: { job_status: "NEW" },
  });
  return data;
}

// POST /jobs/{jobId}/match?profile_id={profileId}
// Runs the AI matching pipeline and returns the updated job.
export async function generateMatch(
  jobId: string,
  profileId: string,
): Promise<JobMatchResponse> {
  const { data } = await apiClient.post<JobMatchResponse>(
    `/jobs/${jobId}/match`,
    null,
    { params: { profile_id: profileId } },
  );
  return data;
}
