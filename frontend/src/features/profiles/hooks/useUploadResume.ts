import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import { toast } from "sonner";
import { uploadResume } from "../api/profiles.service";
import { profilesKeys } from "../api/queryKeys";
import type { ProfileRead } from "@/contracts/profile";
import { getApiErrorMessage } from "@/shared/api/errors";

export function useUploadResume() {
  const queryClient = useQueryClient();

  return useMutation<ProfileRead, AxiosError, File>({
    mutationFn: (file) => uploadResume(file),
    onSuccess: () => {
      toast.success("Профиль создан из резюме");
      queryClient.invalidateQueries({ queryKey: profilesKeys.active() });
    },
    onError: (error) => {
      toast.error("Не удалось загрузить резюме", {
        description: getApiErrorMessage(error),
      });
    },
  });
}
