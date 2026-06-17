// Stable query keys for the jobs-board feature.
export const jobsKeys = {
  all: ["jobs"] as const,
  new: () => [...jobsKeys.all, "NEW"] as const,
  matched: () => [...jobsKeys.all, "MATCHED"] as const,
};
