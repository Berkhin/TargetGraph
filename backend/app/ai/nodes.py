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
from app.ai.state import GraphState
from app.core.logging import get_logger

logger = get_logger(__name__)


class JobRequirementsParsed(BaseModel):
    """Structured extraction target for a single job posting.

    Bound to the model via ``with_structured_output`` so Gemini returns these
    three disjoint buckets directly instead of free-form prose we would have to
    re-parse.
    """

    # Descriptions are deliberately terse: the classification rules live in the
    # system prompt, so each Field only needs a one-line definition of its bucket.
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
    return get_llm().with_structured_output(JobRequirementsParsed)


async def extract_requirements(state: GraphState) -> dict:
    """Pull the list of requirements out of the job description via Gemini.

    Calls the model with structured output, flattens the three extracted
    buckets into a single de-duplicated list of strings, and returns it for
    LangGraph to merge into the state. Any failure (API unavailable, invalid /
    empty model response) is logged and degrades to an empty list so a single
    bad call cannot crash the whole graph.
    """
    logger.info("node", extra={"node": "extract_requirements"})

    if not state.job_text or not state.job_text.strip():
        logger.warning("extract_requirements.empty_job_text")
        return {"extracted_requirements": []}

    try:
        structured_llm = _get_extraction_chain()
        messages = [
            SystemMessage(content=_EXTRACT_SYSTEM_PROMPT),
            HumanMessage(content=state.job_text),
        ]
        parsed: JobRequirementsParsed | None = await structured_llm.ainvoke(messages)
    except Exception:  # noqa: BLE001 — node must never crash the graph
        logger.exception("extract_requirements.failed")
        return {"extracted_requirements": []}

    if parsed is None:
        logger.warning("extract_requirements.no_structured_output")
        return {"extracted_requirements": []}

    # Merge the three buckets into one flat list, trimming blanks and
    # preserving first-seen order while removing duplicates.
    flat: list[str] = []
    seen: set[str] = set()
    for item in (
        *parsed.hard_skills,
        *parsed.soft_skills,
        *parsed.core_responsibilities,
    ):
        cleaned = item.strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            flat.append(cleaned)

    logger.info("extract_requirements.done", extra={"count": len(flat)})
    return {"extracted_requirements": flat}


def match_profile(state: GraphState) -> dict:
    """Score how well the profile matches the extracted requirements."""
    logger.info("node", extra={"node": "match_profile"})
    return {"match_score": 0}


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
