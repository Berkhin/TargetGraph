import { useQuery } from "@tanstack/react-query";
import { getActiveProfile } from "../api/profiles.service";
import { profilesKeys } from "../api/queryKeys";

// Loads the active candidate profile used for AI matching. Replaces the
// previous VITE_ACTIVE_PROFILE_ID hardcode.
export function useActiveProfile() {
  return useQuery({
    queryKey: profilesKeys.active(),
    queryFn: getActiveProfile,
    // A missing profile (404) is a stable state, not a transient error.
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
}
