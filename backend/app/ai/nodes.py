"""Node functions and routing logic for the matching pipeline.

``extract_requirements`` is wired to Gemini via the official
``langchain-google-genai`` integration; the remaining nodes are still LLM-free
stubs that log their name and return the partial state update LangGraph merges
back — they exist to exercise the graph topology and the conditional revision
loop until their real implementations land.

Each node takes the current :class:`GraphState` and returns a ``dict`` of the
fields it wants to update.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.ai.llm import get_llm
from app.ai.state import ExtractedRequirements, GraphState
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


def draft_documents(state: GraphState) -> dict:
    """Draft the resume and cover letter (and bump the revision counter)."""
    logger.info("node", extra={"node": "draft_documents"})
    return {
        "resume_draft": None,
        "cover_letter_draft": None,
        "revision_number": state.revision_number + 1,
    }


def reviewer(state: GraphState) -> dict:
    """Critique the drafts, producing review comments to act on."""
    logger.info("node", extra={"node": "reviewer"})
    return {"review_comments": []}


def should_revise(state: GraphState) -> str:
    """Decide whether to loop back for another draft or finish.

    Loop back to ``draft_documents`` while there are outstanding review comments
    and we are under the revision cap; otherwise terminate the graph.
    """
    if state.review_comments and state.revision_number < 3:
        return "draft_documents"
    return "__end__"
