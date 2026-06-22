import { useQuery } from "@tanstack/react-query";
import { getMatchedJobs } from "../api/jobs.service";
import { jobsKeys } from "../api/queryKeys";

// Loads the postings the AI pipeline matched (status=MATCHED). These carry a
// generated cover_letter_draft. Shared by two views: the jobs board shows the
// not-yet-sent ones (applied_at == null) as ready-to-send cards, and the
// "Отклики" table shows the sent ones (applied_at != null).
export function useMatchedJobs() {
  return useQuery({
    queryKey: jobsKeys.matched(),
    queryFn: getMatchedJobs,
  });
}
