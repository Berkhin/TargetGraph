"""Shared state schema for the LangGraph matching pipeline.

``GraphState`` is the single typed object threaded through every node. Nodes do
not mutate it in place; they return a partial ``dict`` and LangGraph merges the
returned keys back into the state for the next step.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GraphState(BaseModel):
    """End-to-end state for the job/profile matching workflow."""

    # --- Inputs (populated before the graph runs) ---
    job_text: str
    profile_text: str

    # --- Intermediate / output fields (filled in by the nodes) ---
    extracted_requirements: list[str] = Field(default_factory=list)
    match_score: int = 0
    resume_draft: str | None = None
    cover_letter_draft: str | None = None
    review_comments: list[str] = Field(default_factory=list)
    revision_number: int = 0
