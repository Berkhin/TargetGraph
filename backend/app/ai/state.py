"""Shared state schema for the LangGraph matching pipeline.

``GraphState`` is the single typed object threaded through every node. Nodes do
not mutate it in place; they return a partial ``dict`` and LangGraph merges the
returned keys back into the state for the next step.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractedRequirements(BaseModel):
    """The three disjoint requirement buckets parsed from a job posting.

    Doubles as the ``with_structured_output`` target for ``extract_requirements``
    and as the typed field carried through :class:`GraphState`. The buckets are
    kept distinct (not flattened) so downstream nodes can tell a critical hard
    skill apart from a nice-to-have soft skill — ``match_profile`` relies on this
    to penalise missing hard skills more heavily than missing soft ones.
    """

    # Descriptions are deliberately terse: the classification rules live in the
    # extraction system prompt, so each Field only defines its bucket.
    hard_skills: list[str] = Field(
        default_factory=list,
        description="Technical tools, languages, frameworks, platforms, certifications.",
    )
    soft_skills: list[str] = Field(
        default_factory=list,
        description="Interpersonal and behavioural competencies.",
    )
    core_responsibilities: list[str] = Field(
        default_factory=list,
        description="Primary duties and outcomes the role is accountable for.",
    )

    def is_empty(self) -> bool:
        """True when no requirements were extracted into any bucket."""
        return not (self.hard_skills or self.soft_skills or self.core_responsibilities)


class GraphState(BaseModel):
    """End-to-end state for the job/profile matching workflow."""

    # --- Inputs (populated before the graph runs) ---
    job_text: str
    profile_text: str

    # --- Intermediate / output fields (filled in by the nodes) ---
    extracted_requirements: ExtractedRequirements = Field(
        default_factory=ExtractedRequirements
    )
    match_score: int = 0
    # Populated by ``match_profile`` alongside ``match_score`` so downstream
    # nodes (drafting/review) can reason about *what* matched and what is
    # missing, not just the bare number.
    matching_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    match_reasoning: str = ""
    resume_draft: str | None = None
    cover_letter_draft: str | None = None
    review_comments: list[str] = Field(default_factory=list)
    revision_number: int = 0
