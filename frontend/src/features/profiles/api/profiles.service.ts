import { apiClient } from "@/shared/api/client";
import type { ProfileRead, ProfileUpdate } from "@/contracts/profile";

export type { ProfileRead, ProfileUpdate };

// GET /profiles/active — the active candidate profile (404 if none exist).
export async function getActiveProfile(): Promise<ProfileRead> {
  const { data } = await apiClient.get<ProfileRead>("/profiles/active");
  return data;
}

// POST /profiles — create a new profile from JSON data.
export async function createProfile(
  payload: ProfileUpdate,
): Promise<ProfileRead> {
  const { data } = await apiClient.post<ProfileRead>("/profiles", payload);
  return data;
}

// PUT /profiles/{id} — full-aggregate replace of a profile and its children.
export async function updateProfile(
  id: string,
  payload: ProfileUpdate,
): Promise<ProfileRead> {
  const { data } = await apiClient.put<ProfileRead>(`/profiles/${id}`, payload);
  return data;
}

// POST /profiles/upload-resume — create a profile by uploading a PDF resume.
export async function uploadResume(file: File): Promise<ProfileRead> {
  const formData = new FormData();
  formData.append("file", file);

  const { data } = await apiClient.post<ProfileRead>(
    "/profiles/upload-resume",
    formData,
    {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    },
  );
  return data;
}
