import { apiClient } from "@/shared/api/client";
import type { ProfileRead } from "@/contracts/profile";

export type { ProfileRead };

// GET /profiles — all candidate profiles.
export async function getProfiles(): Promise<ProfileRead[]> {
  const { data } = await apiClient.get<ProfileRead[]>("/profiles");
  return data;
}

// GET /profiles/active — the active candidate profile (404 if none exist).
export async function getActiveProfile(): Promise<ProfileRead> {
  const { data } = await apiClient.get<ProfileRead>("/profiles/active");
  return data;
}
