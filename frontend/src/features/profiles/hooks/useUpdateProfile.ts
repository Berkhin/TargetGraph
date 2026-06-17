import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import { toast } from "sonner";
import { updateProfile } from "../api/profiles.service";
import { profilesKeys } from "../api/queryKeys";
import type { ProfileRead, ProfileUpdate } from "@/contracts/profile";
import { getApiErrorMessage } from "@/shared/api/errors";

export type UpdateProfileInput = {
  id: string;
  data: ProfileUpdate;
};

// Persists profile edits via PUT /profiles/{id} and refreshes the cached
// active profile on success.
export function useUpdateProfile() {
  const queryClient = useQueryClient();

  return useMutation<ProfileRead, AxiosError, UpdateProfileInput>({
    mutationFn: ({ id, data }) => updateProfile(id, data),
    onSuccess: () => {
      toast.success("Профиль сохранён");
      queryClient.invalidateQueries({ queryKey: profilesKeys.active() });
    },
    onError: (error) => {
      toast.error("Не удалось сохранить профиль", {
        description: getApiErrorMessage(error),
      });
    },
  });
}
