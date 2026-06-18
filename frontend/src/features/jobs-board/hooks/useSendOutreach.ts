import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  sendOutreachEmail,
  type OutreachSendRequest,
  type OutreachSendResponse,
} from "@/features/jobs-board/api/jobs.service";
import { getApiErrorMessage } from "@/shared/api/errors";

// Sends a cold-outreach email for one posting via the Gmail API. A mutation
// (not a query) because it is a side-effecting one-shot action; success/failure
// are surfaced as toasts so the caller only needs to fire it.
export function useSendOutreach(jobId: string) {
  return useMutation<OutreachSendResponse, unknown, OutreachSendRequest>({
    mutationFn: (payload) => sendOutreachEmail(jobId, payload),
    onSuccess: (res) => {
      toast.success(`Письмо отправлено: ${res.to_email}`);
    },
    onError: (error) => {
      toast.error("Не удалось отправить письмо", {
        description: getApiErrorMessage(error),
      });
    },
  });
}
