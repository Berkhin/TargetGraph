// Stable query keys for the profiles feature.
export const profilesKeys = {
  all: ["profiles"] as const,
  active: () => [...profilesKeys.all, "active"] as const,
};
