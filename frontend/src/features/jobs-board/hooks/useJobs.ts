import { useQuery } from "@tanstack/react-query";
import { getNewJobs } from "../api/jobs.service";
import { jobsKeys } from "../api/queryKeys";

// Loads the list of NEW job postings awaiting AI matching.
export function useJobs() {
  return useQuery({
    queryKey: jobsKeys.new(),
    queryFn: getNewJobs,
  });
}
