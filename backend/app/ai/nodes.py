"""Node functions and routing logic for the matching pipeline.

Every node is wired to Gemini via the official ``langchain-google-genai``
integration and uses ``with_structured_output`` for a guaranteed result shape:
``extract_requirements`` → ``match_profile`` → the parallel pair
``generate_cover_letter`` / ``generate_tailored_cv`` → ``reviewer`` (with the
``should_revise`` revision loop). Each node takes the current :class:`GraphState`
and returns a ``dict`` of the fields it wants LangGraph to merge back.

This module also exposes :func:`evaluate_job_relevance`, a standalone cheap
pre-screen used by the sourcing task *before* the graph runs — it is not a graph
node, just a sibling that reuses the same LLM/chain machinery.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.ai.llm import get_llm
from app.ai.state import (
    ExtractedRequirements,
    GeneratedDocuments,
    GraphState,
    TailoredCV,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class MatchResult(BaseModel):
    """Structured scoring target for a profile/requirements comparison.

    Bound to the model via ``with_structured_output`` so Gemini returns the
    score and its justification directly. The skill buckets make the score
    auditable — they show *which* requirements drove it up or down.
    """

    # No ge/le bound here on purpose: Gemini does not always encode numeric
    # constraints into its function-calling schema, so an out-of-range value
    # would raise a ValidationError inside the chain and the node's ``except``
    # would turn a near-perfect match into 0. We accept the raw int and clamp it
    # to [0, 100] after the call instead.
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

    # No ge/le bound on purpose (same rationale as MatchResult.score): we clamp
    # to [0, 100] after the call rather than risk a ValidationError turning a
    # good match into a dropped row.
    score: int = Field(
        description="Overall fit, 0-100. Reserve 80+ for postings clearly worth applying to.",
    )
    reason: str = Field(
        description="Brief justification (1-2 sentences) for the score.",
    )


# System prompt for the match node. The recruiter persona plus the explicit
# anti-inflation rule are load-bearing: ``with_structured_output`` enforces the
# JSON shape, but only the prompt keeps the score realistic — a low-temperature
# model otherwise gravitates to flattering round numbers.
_MATCH_SYSTEM_PROMPT = (
    "You are a Senior Technical Recruiter scoring how well a candidate's "
    "profile fits a set of job requirements.\n"
    "You are given the extracted REQUIREMENTS and the candidate PROFILE. Each "
    "requirement is tagged with its criticality: [HARD] technical skills are "
    "critical, [soft] and [resp] items are secondary.\n"
    "Rules:\n"
    "- Compare the profile against every requirement individually.\n"
    "- A requirement counts as matched ONLY if the profile gives explicit "
    "evidence for it. Do not assume or infer skills that are not stated.\n"
    "- A related or adjacent technology is NOT a match: e.g. 'FastAPI' does not "
    "satisfy a 'Django' requirement. Count a match only on the same named "
    "technology or an explicit superset of it.\n"
    "- Weight [HARD] requirements far more heavily than [soft]/[resp] ones.\n"
    "- Score bands: 0-30 = major hard-skill gaps; 31-60 = partial fit, key "
    "skills missing; 61-85 = strong fit, minor gaps; 86-100 = reserved for "
    "matching ALL critical hard skills.\n"
    "- If ANY [HARD] requirement is unmet, the score MUST NOT exceed 70.\n"
    "- List the matched requirements in matching_skills and the unmet ones in "
    "missing_skills (most critical first).\n"
    "- Keep reasoning to 1-3 sentences naming the decisive factors."
)


# System prompt for the drafting node. The model speaks AS the candidate (first
# person), so the persona and the no-fabrication rule are the load-bearing parts:
# ``with_structured_output`` only guarantees we get a ``cover_letter`` string back,
# it cannot stop the model inventing experience. The three-paragraph contract and
# the "only what the profile states" rule keep the letter short and truthful.
_DRAFT_SYSTEM_PROMPT = (
    "You are the candidate, writing your own cover letter for the job below. "
    "Write in the first person.\n"
    "Adopt the professional identity, role, and seniority that the CANDIDATE "
    "PROFILE actually supports — never claim a title, seniority, or specialism "
    "the profile does not back up.\n"
    "Structure: exactly three short paragraphs.\n"
    "1. A sharp hook stating, concretely, why you are an excellent fit for this "
    "specific role.\n"
    "2. Specific evidence drawn from your PROFILE that satisfies the job's "
    "REQUIREMENTS — prioritise the hard skills. Name the technologies and the "
    "concrete work that demonstrates them.\n"
    "3. A clear call to action (e.g. inviting a conversation / interview).\n"
    "If REVIEWER FEEDBACK is provided, treat your PREVIOUS DRAFT as the starting "
    "point and revise it to address every point of feedback, keeping the rules "
    "below.\n"
    "Hard rules:\n"
    "- NEVER invent experience, skills, employers, titles, or achievements that "
    "are not stated in the PROFILE. Use only what the profile actually contains.\n"
    "- Keep it concise: three paragraphs maximum, no padding.\n"
    "- Tone: professional, technical, matter-of-fact. No flattery, no clichés, "
    "no exclamation marks, no emotional filler.\n"
    "- Write in the language of the job posting."
)


# System prompt for the extraction node. Kept terse and imperative — the JSON
# shape itself is enforced by ``with_structured_output``, so the prompt only
# needs to define *what* belongs in each bucket and the language policy. The
# "explicitly stated, do not infer" rule is load-bearing: this is strict
# extraction, not requirement inference (no deriving "Python" from "Django").
_EXTRACT_SYSTEM_PROMPT = (
    "You are a technical recruiter parsing a job description. "
    "Classify every requirement into exactly one bucket: "
    "hard_skills, soft_skills, or core_responsibilities.\n"
    "Rules:\n"
    "- Extract ONLY what is explicitly stated in the text. Do not infer, "
    "assume, or add anything not present.\n"
    "- One skill or duty per list item; split compound phrases.\n"
    "- Deduplicate; normalise casing for skill names.\n"
    "- Preserve the source language.\n"
    "- Empty bucket -> empty list."
)


# System prompt for the cheap sourcing pre-screen. Mirrors the match node's
# anti-inflation stance but compressed to a single keep/drop verdict: it runs
# once per newly sourced posting, before the full pipeline, so a low score keeps
# an off-target job off the board and out of the (re-)scraping path.
_RELEVANCE_SYSTEM_PROMPT = (
    "You are a Senior Technical Recruiter doing a fast first-pass screen of a "
    "job posting against a candidate profile.\n"
    "You are given the JOB DESCRIPTION and the candidate PROFILE.\n"
    "Rules:\n"
    "- Score 0-100 how well this candidate fits this specific job.\n"
    "- Weight concrete technical (hard) skills far more heavily than soft "
    "skills or generic responsibilities.\n"
    "- Be strict: a related-but-different technology is NOT a match. Do not "
    "inflate the score for adjacent skills.\n"
    "- Reserve 80+ for postings the candidate is clearly qualified for and "
    "should apply to.\n"
    "- Give a 1-2 sentence reason naming the decisive factors."
)


# System prompt for the tailored-CV node. Like the drafting node it speaks for
# the candidate and is forbidden from inventing experience; the difference is the
# artefact — an ATS-optimised résumé in Markdown, with the existing experience
# bullet points rewritten to surface the job's keywords.
_TAILORED_CV_SYSTEM_PROMPT = (
    "Ты ATS-оптимизатор. Возьми Master Profile кандидата и Job Description. "
    "Перепиши bullet points опыта так, чтобы они максимально резонировали с "
    "ключевыми словами вакансии, не выдумывая несуществующего опыта. Верни "
    "Markdown.\n"
    "Hard rules:\n"
    "- NEVER invent experience, skills, employers, titles, or achievements that "
    "are not stated in the PROFILE. Use only what the profile actually contains.\n"
    "- Mirror the wording of the job's requirements where the profile genuinely "
    "supports it, so an ATS keyword scan matches.\n"
    "- Output valid Markdown only (headings, bullet lists); no commentary."
)


# System prompt for the review node. Strict fact-checking only: the model must
# catch fabrications and unsupported claims grounded in the profile. Styling and
# tone are outside scope — the loop should converge on facts, not synonyms.
_REVIEW_SYSTEM_PROMPT = (
    "You are a Strict Fact-Checker reviewing a cover letter draft. "
    "Your role: identify EVERY hallucination, fabrication, or unsupported claim.\n"
    "You are given the COVER LETTER DRAFT, the CANDIDATE PROFILE, and the JOB "
    "REQUIREMENTS that were extracted from the posting.\n"
    "Rules:\n"
    "- Compare the draft WORD FOR WORD against the PROFILE. Flag ANY skill, title, "
    "employer, achievement, or experience mentioned in the draft that does NOT "
    "appear in the profile.\n"
    "- A fabrication is anything not directly stated in the profile, no matter how "
    "plausible or adjacent (e.g. claiming 'Django' experience when the profile only "
    "mentions 'FastAPI').\n"
    "- IGNORE tone, style, clichés, and emotional language — ONLY flag facts that "
    "contradict the profile or are completely unsupported.\n"
    "- If the draft is accurate and grounded in the profile, "
    "set is_approved=true and leave comments empty.\n"
    "- If there are FACTUAL issues, set is_approved=false and list each problem as a "
    "specific, actionable comment (e.g. 'Fabrication: claims 5 years of Python but "
    "profile shows 2 years').\n"
    "- Be strict about facts, lenient about style."
)


@lru_cache(maxsize=1)
def _get_extraction_chain():
    """Return the cached structured-output chain (base LLM + schema binding).

    ``with_structured_output`` builds a new runnable on each call; binding it
    once here keeps node invocations allocation-free. Tests that swap the LLM
    must clear both caches: ``get_llm.cache_clear()`` and
    ``_get_extraction_chain.cache_clear()``.
    """
    return get_llm().with_structured_output(ExtractedRequirements)


@lru_cache(maxsize=1)
def _get_match_chain():
    """Return the cached structured-output chain for profile matching.

    Same caching contract as :func:`_get_extraction_chain`: tests swapping the
    LLM must also call ``_get_match_chain.cache_clear()``.
    """
    return get_llm().with_structured_output(MatchResult)


@lru_cache(maxsize=1)
def _get_draft_chain():
    """Return the cached structured-output chain for document drafting.

    Same caching contract as :func:`_get_extraction_chain`: tests swapping the
    LLM must also call ``_get_draft_chain.cache_clear()``.
    """
    return get_llm().with_structured_output(GeneratedDocuments)


@lru_cache(maxsize=1)
def _get_review_chain():
    """Return the cached structured-output chain for reviewing drafts.

    Same caching contract as :func:`_get_extraction_chain`: tests swapping the
    LLM must also call ``_get_review_chain.cache_clear()``.
    """
    return get_llm().with_structured_output(ReviewResult)


@lru_cache(maxsize=1)
def _get_relevance_chain():
    """Return the cached structured-output chain for the sourcing pre-screen.

    Same caching contract as :func:`_get_extraction_chain`: tests swapping the
    LLM must also call ``_get_relevance_chain.cache_clear()``.
    """
    return get_llm().with_structured_output(RelevanceResult)


@lru_cache(maxsize=1)
def _get_tailored_cv_chain():
    """Return the cached structured-output chain for tailored-CV generation.

    Same caching contract as :func:`_get_extraction_chain`: tests swapping the
    LLM must also call ``_get_tailored_cv_chain.cache_clear()``.
    """
    return get_llm().with_structured_output(TailoredCV)


def _dedupe(items: list[str]) -> list[str]:
    """Trim blanks and drop case-insensitive duplicates, keeping first-seen order."""
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = item.strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


async def extract_requirements(state: GraphState) -> dict:
    """Pull the structured requirements out of the job description via Gemini.

    Calls the model with structured output and returns the three requirement
    buckets (de-duplicated, blanks trimmed) for LangGraph to merge into the
    state. Keeping the buckets separate — rather than flattening to one list —
    lets ``match_profile`` weight critical hard skills correctly. Any failure
    (API unavailable, invalid / empty model response) is logged and degrades to
    empty buckets so a single bad call cannot crash the whole graph.
    """
    logger.info("node", extra={"node": "extract_requirements"})

    if not state.job_text or not state.job_text.strip():
        logger.warning("extract_requirements.empty_job_text")
        return {"extracted_requirements": ExtractedRequirements()}

    try:
        structured_llm = _get_extraction_chain()
        messages = [
            SystemMessage(content=_EXTRACT_SYSTEM_PROMPT),
            HumanMessage(content=state.job_text),
        ]
        parsed: ExtractedRequirements | None = await structured_llm.ainvoke(messages)
    except Exception:  # noqa: BLE001 — node must never crash the graph
        logger.exception("extract_requirements.failed")
        return {"extracted_requirements": ExtractedRequirements()}

    if parsed is None:
        logger.warning("extract_requirements.no_structured_output")
        return {"extracted_requirements": ExtractedRequirements()}

    # Clean each bucket independently: trim blanks and drop case-insensitive
    # duplicates while preserving first-seen order.
    cleaned = ExtractedRequirements(
        hard_skills=_dedupe(parsed.hard_skills),
        soft_skills=_dedupe(parsed.soft_skills),
        core_responsibilities=_dedupe(parsed.core_responsibilities),
    )

    total = (
        len(cleaned.hard_skills)
        + len(cleaned.soft_skills)
        + len(cleaned.core_responsibilities)
    )
    logger.info("extract_requirements.done", extra={"count": total})
    return {"extracted_requirements": cleaned}


async def match_profile(state: GraphState) -> dict:
    """Score how well the profile matches the extracted requirements via Gemini.

    Sends the extracted requirements and the candidate profile to the model
    with structured output, returning the score plus the matched/missing skill
    buckets for LangGraph to merge into the state. Any failure (API
    unavailable, invalid / empty model response) is logged and degrades to a
    zero score so the graph can still route safely to the end.
    """
    logger.info("node", extra={"node": "match_profile"})

    # Nothing to compare against -> a zero score, surfaced explicitly rather
    # than spending an API call that can only return 0.
    if not state.profile_text or not state.profile_text.strip():
        logger.warning("match_profile.empty_profile_text")
        return {"match_score": 0, "match_reasoning": "No profile provided."}
    reqs = state.extracted_requirements
    if reqs.is_empty():
        logger.warning("match_profile.no_requirements")
        return {"match_score": 0, "match_reasoning": "No requirements extracted."}

    # Tag each requirement with its criticality so the model can apply the
    # hard-skill weighting the system prompt asks for — without these labels the
    # buckets are indistinguishable and the anti-inflation rule is unenforceable.
    requirement_lines = [
        *(f"- [HARD] {s}" for s in reqs.hard_skills),
        *(f"- [soft] {s}" for s in reqs.soft_skills),
        *(f"- [resp] {s}" for s in reqs.core_responsibilities),
    ]
    human_content = (
        "REQUIREMENTS:\n"
        + "\n".join(requirement_lines)
        + f"\n\nPROFILE:\n{state.profile_text}"
    )

    try:
        structured_llm = _get_match_chain()
        messages = [
            SystemMessage(content=_MATCH_SYSTEM_PROMPT),
            HumanMessage(content=human_content),
        ]
        result: MatchResult | None = await structured_llm.ainvoke(messages)
    except Exception:  # noqa: BLE001 — node must never crash the graph
        logger.exception("match_profile.failed")
        return {"match_score": 0, "match_reasoning": "Error during LLM evaluation."}

    if result is None:
        logger.warning("match_profile.no_structured_output")
        return {
            "match_score": 0,
            "match_reasoning": "LLM returned no structured output.",
        }

    # Clamp defensively: the model can return values outside 0-100, and we would
    # rather cap a near-perfect match than discard it (see MatchResult.score).
    score = max(0, min(100, result.score))
    logger.info("match_profile.done", extra={"score": score})
    return {
        "match_score": score,
        "matching_skills": result.matching_skills,
        "missing_skills": result.missing_skills,
        "match_reasoning": result.reasoning,
    }


async def generate_cover_letter(state: GraphState) -> dict:
    """Draft the cover letter via Gemini.

    The model writes in the first person as the candidate, grounded strictly in
    ``profile_text`` and the requirements ``extract_requirements`` already
    surfaced — the system prompt forbids inventing experience. Runs in parallel
    with :func:`generate_tailored_cv` after ``match_profile`` and is the node the
    reviewer revision loop targets. Any failure (API unavailable, invalid /
    empty model response) is logged and degrades to a placeholder so the graph
    can still route on to review and terminate.
    """
    logger.info("node", extra={"node": "generate_cover_letter"})

    # The placeholder every early/error path returns. The revision counter is
    # incremented only in the reviewer node (the loop's exit point), not here.
    def _fallback() -> dict:
        return {"cover_letter_draft": "Error generating document."}

    # Refuse to write without grounding. A cover letter is pure fabrication
    # without a profile to draw from, and untailorable without a job posting —
    # no prompt rule stops the model inventing both, so we guard like the sibling
    # nodes do rather than spend an API call that can only hallucinate.
    if not state.profile_text or not state.profile_text.strip():
        logger.warning("generate_cover_letter.empty_profile_text")
        return _fallback()
    if not state.job_text or not state.job_text.strip():
        logger.warning("generate_cover_letter.empty_job_text")
        return _fallback()

    # Hand the model the same three inputs the prompt promises: the vacancy, the
    # candidate profile, and the requirements isolated on the previous step
    # (tagged by criticality so the letter can lead with the hard skills).
    reqs = state.extracted_requirements
    requirement_lines = [
        *(f"- [HARD] {s}" for s in reqs.hard_skills),
        *(f"- [soft] {s}" for s in reqs.soft_skills),
        *(f"- [resp] {s}" for s in reqs.core_responsibilities),
    ]
    requirements_block = "\n".join(requirement_lines) or "(none extracted)"
    human_content = (
        f"JOB POSTING:\n{state.job_text}\n\n"
        f"EXTRACTED REQUIREMENTS:\n{requirements_block}\n\n"
        f"CANDIDATE PROFILE:\n{state.profile_text}"
    )

    # On a revision pass ``should_revise`` routes us back here with the reviewer's
    # comments and the prior draft. Feed both in so the model actually improves
    # the letter instead of regenerating an identical one (low temperature) and
    # burning a revision on it. On the first pass both are empty -> skipped.
    if state.review_comments:
        feedback_block = "\n".join(f"- {c}" for c in state.review_comments)
        human_content += (
            f"\n\nPREVIOUS DRAFT:\n{state.cover_letter_draft or ''}"
            f"\n\nREVIEWER FEEDBACK (address every point):\n{feedback_block}"
        )

    logger.info("generate_cover_letter.prompt", extra={"chars": len(human_content)})

    try:
        structured_llm = _get_draft_chain()
        messages = [
            SystemMessage(content=_DRAFT_SYSTEM_PROMPT),
            HumanMessage(content=human_content),
        ]
        result: GeneratedDocuments | None = await structured_llm.ainvoke(messages)
    except Exception:  # noqa: BLE001 — node must never crash the graph
        logger.exception("generate_cover_letter.failed")
        return _fallback()

    # Treat a missing or blank letter as a failure: structured output can return
    # an empty ``cover_letter`` that would otherwise be reported as success and
    # shown to the user as an empty draft.
    if result is None or not result.cover_letter.strip():
        logger.warning("generate_cover_letter.no_structured_output")
        return _fallback()

    logger.info("generate_cover_letter.done")
    return {"cover_letter_draft": result.cover_letter}


async def generate_tailored_cv(state: GraphState) -> dict:
    """Generate an ATS-optimised résumé via Gemini.

    Runs in parallel with :func:`generate_cover_letter` after ``match_profile``.
    The model rewrites the candidate's existing experience bullet points to
    resonate with the job's keywords, grounded strictly in ``profile_text`` (the
    prompt forbids inventing experience). Writes the disjoint ``tailored_cv``
    state key so it never collides with the cover-letter node's concurrent
    update. Any failure is logged and degrades to ``None`` so the graph still
    terminates and the cover-letter branch is unaffected.
    """
    logger.info("node", extra={"node": "generate_tailored_cv"})

    # Refuse to write without grounding — a résumé is pure fabrication without a
    # profile, and untailorable without a job posting.
    if not state.profile_text or not state.profile_text.strip():
        logger.warning("generate_tailored_cv.empty_profile_text")
        return {"tailored_cv": None}
    if not state.job_text or not state.job_text.strip():
        logger.warning("generate_tailored_cv.empty_job_text")
        return {"tailored_cv": None}

    reqs = state.extracted_requirements
    requirement_lines = [
        *(f"- [HARD] {s}" for s in reqs.hard_skills),
        *(f"- [soft] {s}" for s in reqs.soft_skills),
        *(f"- [resp] {s}" for s in reqs.core_responsibilities),
    ]
    requirements_block = "\n".join(requirement_lines) or "(none extracted)"
    human_content = (
        f"JOB POSTING:\n{state.job_text}\n\n"
        f"EXTRACTED REQUIREMENTS:\n{requirements_block}\n\n"
        f"CANDIDATE PROFILE (Master Profile):\n{state.profile_text}"
    )

    logger.info("generate_tailored_cv.prompt", extra={"chars": len(human_content)})

    try:
        structured_llm = _get_tailored_cv_chain()
        messages = [
            SystemMessage(content=_TAILORED_CV_SYSTEM_PROMPT),
            HumanMessage(content=human_content),
        ]
        result: TailoredCV | None = await structured_llm.ainvoke(messages)
    except Exception:  # noqa: BLE001 — node must never crash the graph
        logger.exception("generate_tailored_cv.failed")
        return {"tailored_cv": None}

    if result is None or not result.tailored_cv.strip():
        logger.warning("generate_tailored_cv.no_structured_output")
        return {"tailored_cv": None}

    logger.info("generate_tailored_cv.done")
    return {"tailored_cv": result.tailored_cv}


async def reviewer(state: GraphState) -> dict:
    """Fact-check the cover letter draft against the profile via Gemini.

    Sends the draft, candidate profile, and extracted requirements to the model
    with structured output, returning approval status and any comments about
    hallucinations, fabrications, or tone issues. Any failure (API unavailable,
    invalid / empty model response) is logged and degrades to approved (empty
    comments) so the graph can still route safely to the end.
    """
    logger.info("node", extra={"node": "reviewer"})

    # Guard against empty draft: skip review if there is nothing to review.
    if not state.cover_letter_draft or not state.cover_letter_draft.strip():
        logger.warning("reviewer.empty_draft")
        return {"review_comments": []}

    # Guard against missing profile: cannot fact-check without grounding.
    if not state.profile_text or not state.profile_text.strip():
        logger.warning("reviewer.empty_profile_text")
        return {"review_comments": []}

    # Build the human prompt: draft, profile, and extracted requirements so the
    # reviewer can check against all three sources.
    reqs = state.extracted_requirements
    requirement_lines = [
        *(f"- [HARD] {s}" for s in reqs.hard_skills),
        *(f"- [soft] {s}" for s in reqs.soft_skills),
        *(f"- [resp] {s}" for s in reqs.core_responsibilities),
    ]
    requirements_block = "\n".join(requirement_lines) or "(none extracted)"
    human_content = (
        f"COVER LETTER DRAFT:\n{state.cover_letter_draft}\n\n"
        f"EXTRACTED REQUIREMENTS:\n{requirements_block}\n\n"
        f"CANDIDATE PROFILE:\n{state.profile_text}"
    )

    logger.info("reviewer.prompt", extra={"chars": len(human_content)})

    try:
        structured_llm = _get_review_chain()
        messages = [
            SystemMessage(content=_REVIEW_SYSTEM_PROMPT),
            HumanMessage(content=human_content),
        ]
        result: ReviewResult | None = await structured_llm.ainvoke(messages)
    except Exception:  # noqa: BLE001 — node must never crash the graph
        logger.exception("reviewer.failed")
        # On critical API failure, cap the loop at 3 attempts even with retries.
        return {
            "review_comments": [],
            "revision_number": min(state.revision_number + 1, 3),
        }

    if result is None:
        logger.warning("reviewer.no_structured_output")
        return {
            "review_comments": [],
            "revision_number": min(state.revision_number + 1, 3),
        }

    # Extract comments; deduplicate and trim blanks.
    comments = _dedupe(result.comments) if result.comments else []

    logger.info(
        "reviewer.done",
        extra={"is_approved": result.is_approved, "comment_count": len(comments)},
    )
    # Increment revision counter (the single point where loop attempts are tracked).
    return {
        "review_comments": comments,
        "revision_number": state.revision_number + 1,
    }


def should_draft(state: GraphState) -> list[str] | str:
    """Gate drafting on the match score, right after ``match_profile``.

    A job scoring below ``score_threshold`` will be rejected regardless of how
    good its cover letter is, so there is no point spending LLM calls drafting
    one. Below the threshold we route straight to the end; at/above it we fan out
    to both drafting nodes in parallel (returning the two targets as a list is
    how LangGraph triggers a parallel fan-out from a conditional edge).
    """
    if state.match_score < state.score_threshold:
        logger.info(
            "should_draft.skip",
            extra={"score": state.match_score, "threshold": state.score_threshold},
        )
        return "__end__"
    return ["generate_cover_letter", "generate_tailored_cv"]


def should_revise(state: GraphState) -> str:
    """Decide whether to loop back for another draft or finish.

    Loop back to ``generate_cover_letter`` while there are outstanding review
    comments (non-empty after stripping) and we are under the revision cap;
    otherwise terminate the graph. The CV branch is never revised — only the
    cover letter is fact-checked by the reviewer.
    """
    meaningful_comments = [c for c in (state.review_comments or []) if c.strip()]
    if meaningful_comments and state.revision_number < 3:
        return "generate_cover_letter"
    return "__end__"


async def evaluate_job_relevance(job_description: str, profile_data: str) -> dict:
    """Cheap pre-screen of one posting against a profile, before the full pipeline.

    Called by the sourcing task for each *newly sourced* posting (after dedup, so
    it never re-scores known jobs). Returns ``{"score": int, "reason": str}`` for
    a clear match/drop decision.

    Fail-open: on any error, empty input, or missing structured output it returns
    ``{"score": None, "reason": ...}``. The caller keeps such postings as ``NEW``
    rather than dropping them, so a Gemini outage degrades to "let the full
    pipeline decide later" instead of silently discarding every sourced job.
    """
    if not job_description or not job_description.strip():
        return {"score": None, "reason": "Empty job description."}
    if not profile_data or not profile_data.strip():
        return {"score": None, "reason": "Empty profile."}

    human_content = (
        f"JOB DESCRIPTION:\n{job_description}\n\nPROFILE:\n{profile_data}"
    )
    try:
        structured_llm = _get_relevance_chain()
        messages = [
            SystemMessage(content=_RELEVANCE_SYSTEM_PROMPT),
            HumanMessage(content=human_content),
        ]
        result: RelevanceResult | None = await structured_llm.ainvoke(messages)
    except Exception:  # noqa: BLE001 — pre-screen must never crash the sourcing task
        logger.exception("evaluate_job_relevance.failed")
        return {"score": None, "reason": "Pre-screen unavailable."}

    if result is None:
        logger.warning("evaluate_job_relevance.no_structured_output")
        return {"score": None, "reason": "Pre-screen returned no structured output."}

    # Clamp defensively (see RelevanceResult.score / MatchResult.score).
    score = max(0, min(100, result.score))
    return {"score": score, "reason": result.reason}
