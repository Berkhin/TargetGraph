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

    def to_prompt_block(self) -> str:
        """Render the buckets as a single tagged block for the LLM prompts.

        Each line is criticality-tagged (``[HARD]`` / ``[soft]`` / ``[resp]``) so
        downstream nodes can lead with the hard skills. Shared by every node that
        feeds the requirements to the model (match / draft / tailored-CV / review)
        so the tag format has a single source of truth.
        """
        lines = [
            *(f"- [HARD] {s}" for s in self.hard_skills),
            *(f"- [soft] {s}" for s in self.soft_skills),
            *(f"- [resp] {s}" for s in self.core_responsibilities),
        ]
        return "\n".join(lines) or "(none extracted)"


class GeneratedDocuments(BaseModel):
    """Structured output target for the ``generate_cover_letter`` node.

    Bound to the model via ``with_structured_output`` so Gemini returns the
    cover letter as a single field rather than free-form prose we would have to
    parse out of a chat message. Kept as its own model (not just a bare ``str``)
    so additional drafted artefacts (e.g. a tailored resume) can be added later
    without changing the node's call signature.
    """

    cover_letter: str = Field(
        description="The full cover letter text, ready to send (max 3 paragraphs).",
    )


class TailoredCV(BaseModel):
    """Structured output target for the ``generate_tailored_cv`` node.

    Bound to the model via ``with_structured_output`` so Gemini returns the
    tailored résumé as a single Markdown field rather than free-form prose.
    """

    tailored_cv: str = Field(
        description="ATS-optimised résumé in Markdown, rewritten to resonate with "
        "the job's keywords without inventing experience.",
    )


class MatchResult(BaseModel):
    """Structured scoring target for a profile/requirements comparison.

    Bound to the model via ``with_structured_output`` so Gemini returns the
    score and its justification directly. The skill buckets make the score
    auditable — they show *which* requirements drove it up or down.
    """

    score: int = Field(
        description="Overall fit, 0-100. Reserve 90+ for near-perfect matches.",
    )
    matching_skills: list[str] = Field(
        default_factory=list,
        description="Requirements clearly evidenced in the candidate profile.",
    )
    missing_skills: list[str] = Field(
        default_factory=list,
        description="Requirements absent from the profile, critical ones first.",
    )
    reasoning: str = Field(
        description="Brief justification (1-3 sentences) for the score.",
    )


class ReviewResult(BaseModel):
    """Structured output target for the ``reviewer`` node.

    Captures whether the draft cover letter is ready for submission and any
    factual or stylistic issues that need addressing. An empty ``comments``
    list signals approval.
    """

    is_approved: bool = Field(
        description="True if the cover letter is ready to send (no hallucinations, professional tone).",
    )
    comments: list[str] = Field(
        default_factory=list,
        description="Specific hallucinations, fabrications, or stylistic issues (empty if approved).",
    )


class RelevanceResult(BaseModel):
    """Structured output target for the cheap sourcing pre-screen.

    Bound to the model via ``with_structured_output`` so Gemini returns a fit
    score and a one-line reason directly. Deliberately lighter than
    :class:`MatchResult` — it runs once per *newly sourced* posting before the
    expensive matching pipeline, so it only needs a coarse keep/drop signal.
    """

    score: int = Field(
        description="Relevance 0-100. Under 55 = clearly off-target (wrong field "
        "/ no overlap); 55+ = plausibly worth showing to the candidate.",
    )
    reason: str = Field(
        description="Brief justification (1-2 sentences) for the score.",
    )


class GraphState(BaseModel):
    """End-to-end state for the job/profile matching workflow."""

    # --- Inputs (populated before the graph runs) ---
    job_text: str
    profile_text: str
    # Employer identity for the cold-outreach (recruiter lookup) node. The graph
    # is otherwise DB-agnostic, but ``find_recruiter_contact`` needs a company to
    # query Hunter. Lookup precedence: ``company_website`` (the employer's real
    # domain, most accurate) -> a real domain parsed from ``source_url`` -> the
    # company name. All default empty so the node degrades gracefully (no lookup)
    # when the orchestrator omits them.
    company_name: str = ""
    source_url: str = ""
    # The employer's own website (Apify ``companyWebsite``), e.g.
    # "https://www.gini-apps.com" — the preferred Hunter lookup key.
    company_website: str | None = None
    # Minimum match score to keep drafting. Below this the graph short-circuits
    # right after ``match_profile`` — no cover letter / CV is generated for a job
    # that will be rejected anyway, saving the LLM calls (and quota). Defaults to
    # the service's MATCHED threshold; the orchestrator injects the real value.
    score_threshold: int = 50

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
    # Cold-outreach contact resolved by ``find_recruiter_contact`` (Hunter.io)
    # before the cover letter is drafted. Both stay None when no named recruiter
    # is found, in which case the cover letter falls back to a generic greeting.
    recruiter_name: str | None = None
    recruiter_email: str | None = None
    cover_letter_draft: str | None = None
    # ATS-optimised résumé produced by ``generate_tailored_cv`` in parallel with
    # the cover letter. Disjoint from ``cover_letter_draft`` so both nodes can
    # write the state concurrently without a reducer.
    tailored_cv: str | None = None
    review_comments: list[str] = Field(default_factory=list)
    revision_number: int = 0
    # Set when ``generate_cover_letter`` could not produce a draft (LLM error /
    # quota). Lets ``should_revise`` stop instead of looping a failing drafter,
    # and lets the service avoid persisting a broken MATCHED result.
    drafting_failed: bool = False
    # Set when an *analysis* node (``extract_requirements`` / ``match_profile``)
    # failed on an LLM/quota error rather than a genuine no-match. Lets the service
    # avoid persisting a false REJECTED verdict for a job it never really scored.
    analysis_failed: bool = False
