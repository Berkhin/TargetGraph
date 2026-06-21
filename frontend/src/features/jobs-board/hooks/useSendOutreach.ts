import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  sendOutreachEmail,
  type OutreachSendRequest,
  type OutreachSendResponse,
} from "@/features/jobs-board/api/jobs.service";
import { jobsKeys } from "@/features/jobs-board/api/queryKeys";
import { getApiErrorMessage } from "@/shared/api/errors";

// Sends a cold-outreach email for one posting via the Gmail API. A mutation
// (not a query) because it is a side-effecting one-shot action; success/failure
// are surfaced as toasts so the caller only needs to fire it.
export function useSendOutreach(jobId: string) {
  const queryClient = useQueryClient();
  return useMutation<OutreachSendResponse, unknown, OutreachSendRequest>({
    mutationFn: (payload) => sendOutreachEmail(jobId, payload),
    onSuccess: (res) => {
      toast.success(`Письмо отправлено: ${res.to_email}`);
      // The backend stamped applied_at; refetch the MATCHED list so the card
      // re-renders with the "Подано · date" marker (its key includes
      // updated_at, which changed, so it remounts).
      void queryClient.invalidateQueries({ queryKey: jobsKeys.matched() });
    },
    onError: (error) => {
      toast.error("Не удалось отправить письмо", {
        description: getApiErrorMessage(error),
      });
    },
  });
}
