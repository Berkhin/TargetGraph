import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { deleteJob } from "@/features/jobs-board/api/jobs.service";
import { jobsKeys } from "@/features/jobs-board/api/queryKeys";
import { getApiErrorMessage } from "@/shared/api/errors";

// Soft-deletes one posting (backend marks it DISCARDED). A mutation because it
// is a side-effecting one-shot action; success/failure surface as toasts. On
// success both boards are invalidated — a card can live on the NEW feed or the
// MATCHED "Отклики" list — so the removed card disappears without a reload.
export function useDeleteJob(jobId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, unknown, void>({
    mutationFn: () => deleteJob(jobId),
    onSuccess: () => {
      toast.success("Карточка удалена");
      void queryClient.invalidateQueries({ queryKey: jobsKeys.matched() });
      void queryClient.invalidateQueries({ queryKey: jobsKeys.new() });
    },
    onError: (error) => {
      toast.error("Не удалось удалить карточку", {
        description: getApiErrorMessage(error),
      });
    },
  });
}
