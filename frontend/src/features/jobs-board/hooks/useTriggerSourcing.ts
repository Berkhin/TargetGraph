import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import { toast } from "sonner";
import { triggerSourcing } from "../api/jobs.service";
import { jobsKeys } from "../api/queryKeys";
import { getApiErrorMessage } from "@/shared/api/errors";

export function useTriggerSourcing() {
  const queryClient = useQueryClient();

  return useMutation<{ status: string; message: string }, AxiosError>({
    mutationFn: () => triggerSourcing(),
    onSuccess: () => {
      toast.success("Sourcing job started", {
        description: "Looking for new job postings...",
      });
      queryClient.invalidateQueries({ queryKey: jobsKeys.all });
    },
    onError: (error) => {
      toast.error("Failed to trigger sourcing", {
        description: getApiErrorMessage(error),
      });
    },
  });
}
