import { useQuery } from "@tanstack/react-query";
import { getMatchedJobs } from "../api/jobs.service";
import { jobsKeys } from "../api/queryKeys";

// Loads the postings the AI pipeline matched (status=MATCHED). These carry a
// generated cover_letter_draft, surfaced on the "Отклики" page.
export function useMatchedJobs() {
  return useQuery({
    queryKey: jobsKeys.matched(),
    queryFn: getMatchedJobs,
  });
}
