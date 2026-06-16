import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import { toast } from "sonner";
import { generateMatch } from "../api/jobs.service";
import { jobsKeys } from "../api/queryKeys";
import type { JobMatchResponse } from "../api/types";
import { getApiErrorMessage } from "@/shared/api/errors";

export type MatchJobInput = {
  jobId: string;
  profileId: string;
};

// Runs the AI matching pipeline for a job. On success the job leaves the
// NEW list (it becomes MATCHED or REJECTED_BY_AI), so we invalidate the
// list query to refetch. Errors surface as a toast.
export function useMatchJob() {
  const queryClient = useQueryClient();

  return useMutation<JobMatchResponse, AxiosError, MatchJobInput>({
    mutationFn: ({ jobId, profileId }) => generateMatch(jobId, profileId),
    onSuccess: (job) => {
      toast.success(
        job.status === "MATCHED"
          ? `Отклик готов (совпадение ${job.match_score ?? "—"}%)`
          : "Вакансия отклонена ИИ",
      );
      // Drop the now-non-NEW job from the feed.
      queryClient.invalidateQueries({ queryKey: jobsKeys.new() });
    },
    onError: (error) => {
      toast.error("Не удалось сгенерировать отклик", {
        description: getApiErrorMessage(error),
      });
    },
  });
}
