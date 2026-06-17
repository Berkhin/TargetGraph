// Strict API contract for the Master Profile aggregate.
// Mirrors backend/app/models/schemas/profile.py (ProfileRead).
// Project convention: `type` only — no `interface`, no `any`.

export type ExperienceRead = {
  id: string;
  company: string;
  role: string;
  highlights: string[];
  start_date: string;
  end_date: string | null;
};

export type SkillRead = {
  id: string;
  category: string;
  skills: string[];
};

// GET /api/v1/profiles — mirrors ProfileRead.
export type ProfileRead = {
  id: string;
  candidate_name: string;
  target_titles: string[];
  preferences: Record<string, unknown>;
  experiences: ExperienceRead[];
  skills: SkillRead[];
};

// Child write shapes — like the *Read types but without the server-generated id.
export type ExperienceWrite = Omit<ExperienceRead, "id">;
export type SkillWrite = Omit<SkillRead, "id">;

// PUT /api/v1/profiles/{id} — mirrors backend ProfileUpdate. A full-aggregate
// replace: nested experiences/skills are written wholesale (no child ids).
export type ProfileUpdate = {
  candidate_name: string;
  target_titles: string[];
  preferences: Record<string, unknown>;
  experiences: ExperienceWrite[];
  skills: SkillWrite[];
};
