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
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.ai.llm import get_llm
from app.ai.state import (
    ExtractedRequirements,
    GeneratedDocuments,
    GraphState,
    TailoredCV,
)
from app.core.config import get_ai_settings
from app.core.logging import get_logger
from app.services.hunter_client import HunterClient

logger = get_logger(__name__)

# Job-board / ATS hosts that appear in a posting's ``source_url`` but are NEVER
# the employer's own domain — so Hunter must not be queried with them. When the
# source URL resolves to one of these (the LinkedIn sourcing pipeline always
# does), the recruiter lookup falls back to the company *name* instead.
_NON_EMPLOYER_HOSTS = frozenset(
    {
        "linkedin.com",
        "indeed.com",
        "glassdoor.com",
        "ziprecruiter.com",
        "monster.com",
        "dice.com",
        "lever.co",
        "greenhouse.io",
        "workable.com",
        "smartrecruiters.com",
        "bamboohr.com",
    }
)


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
        description="Relevance 0-100. Under 55 = clearly off-target (wrong field "
        "/ no overlap); 55+ = plausibly worth showing to the candidate.",
    )
    reason: str = Field(
        description="Brief justification (1-2 sentences) for the score.",
    )


# Strict scoring rubric for the full match node (``_MATCH_SYSTEM_PROMPT``) only.
# This is the *qualification* verdict — it answers "is the candidate actually a
# fit?" and is deliberately harsh (hard-skill cap, no credit for adjacent tech).
# The sourcing pre-screen does NOT use this: it asks the looser "is this posting
# even relevant?" question (see ``_RELEVANCE_SYSTEM_PROMPT``), so a borderline job
# stays on the board and the strict match decides it later, on click.
_SCORING_RUBRIC = (
    "Judge OVERALL fit holistically — the whole candidate against the whole "
    "role (field, seniority, domain, responsibilities, tech stack, and career "
    "trajectory). Do NOT score as a checklist of individual skills.\n"
    "- Neither document is exhaustive: a posting lists only some of its "
    "requirements, and a CV describes only some of the candidate's experience. "
    "Reward transferable, adjacent, and clearly implied skills; do NOT penalise "
    "a missing keyword when the overall background plainly covers it (e.g. "
    "strong FastAPI experience reasonably covers a generic 'web framework' or "
    "even a 'Django' need).\n"
    "- A few unmet requirements are normal and must NOT cap the score when the "
    "candidate is a sensible overall match for the role.\n"
    "- Weigh decisive misfits heavily (wrong profession, far-off seniority, no "
    "real domain overlap), but treat individual missing tools as minor.\n"
    "- Score bands (overall fit): 0-30 = wrong field / fundamentally unsuitable; "
    "31-49 = weak, only partial overlap; 50-69 = reasonable fit, worth applying "
    "despite some gaps; 70-85 = strong fit; 86-100 = excellent, near-ideal fit."
)


# System prompt for the match node. The recruiter persona plus the explicit
# anti-inflation rule are load-bearing: ``with_structured_output`` enforces the
# JSON shape, but only the prompt keeps the score realistic — a low-temperature
# model otherwise gravitates to flattering round numbers.
_MATCH_SYSTEM_PROMPT = (
    "You are a Senior Technical Recruiter judging how well a candidate fits a "
    "role OVERALL.\n"
    "You are given the full JOB POSTING, a list of extracted KEY REQUIREMENTS "
    "(reference only — [HARD] = technical, [soft]/[resp] = secondary), and the "
    "full candidate PROFILE.\n"
    "Form a single holistic judgment of overall fit — read both sides as a whole, "
    "not as a per-skill tally.\n"
    "Rules:\n"
    + _SCORING_RUBRIC
    + "\n"
    "- In matching_skills list the main strengths that make the candidate a fit; "
    "in missing_skills list only the most notable genuine gaps (may be empty).\n"
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
    "Open with a salutation line: if a RECIPIENT NAME is provided, greet that "
    "person by their first name (e.g. 'Dear Anna,'); if none is provided, use a "
    "generic 'Dear Hiring Team,'. Translate the greeting into the posting's "
    "language. Never invent or guess a recipient name.\n"
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


# System prompt for the cheap sourcing pre-screen. This is a coarse RELEVANCE
# gate, NOT a qualification verdict (that is the match node's job, on click). It
# is deliberately GENEROUS: its only purpose is to drop clearly off-target
# postings (a different profession, no meaningful overlap) so the board is not
# flooded with noise — borderline jobs the candidate could plausibly apply to
# must stay. Hence: no hard-skill cap, and adjacent/transferable skills count.
_RELEVANCE_SYSTEM_PROMPT = (
    "You are a Senior Technical Recruiter doing a fast RELEVANCE screen of a job "
    "posting against a candidate profile. This is a coarse keep/drop gate before "
    "a separate, stricter qualification match — so be GENEROUS: the goal is to "
    "drop only clearly-irrelevant postings, not to judge full qualification.\n"
    "You are given the JOB DESCRIPTION and the candidate PROFILE.\n"
    "Rules:\n"
    "- Score 0-100 how RELEVANT this posting is to the candidate's field, target "
    "roles, and overall skill set.\n"
    "- Count transferable and adjacent skills as positives (a related framework, "
    "language, or domain still signals relevance). Missing one or two required "
    "skills is fine — do NOT cap or heavily penalise for it.\n"
    "- Score under 55 ONLY when the posting is a different profession or shares "
    "almost no overlap with the candidate's background (e.g. a Mechanical or "
    "Process Engineer role for a Software Engineer).\n"
    "- Give 55+ to any posting in the candidate's field with real or transferable "
    "overlap that is plausibly worth applying to.\n"
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
    """Return the cached structured-output chain for cover-letter drafting.

    Uses the pro-tier generation model at the cover-letter temperature (higher,
    for a natural voice). Same caching contract as :func:`_get_extraction_chain`:
    tests swapping the LLM must also call ``_get_draft_chain.cache_clear()``.
    """
    settings = get_ai_settings()
    return get_llm(
        model=settings.gemini_generation_model,
        temperature=settings.gemini_cover_letter_temperature,
    ).with_structured_output(GeneratedDocuments)


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

    Uses the pro-tier generation model at the (low) tailored-CV temperature, to
    keep the rewritten experience factual and avoid hallucinating skills. Same
    caching contract as :func:`_get_extraction_chain`: tests swapping the LLM
    must also call ``_get_tailored_cv_chain.cache_clear()``.
    """
    settings = get_ai_settings()
    return get_llm(
        model=settings.gemini_generation_model,
        temperature=settings.gemini_tailored_cv_temperature,
    ).with_structured_output(TailoredCV)


def _clamp_score(score: int) -> int:
    """Clamp a model-returned score to [0, 100].

    Gemini can return values outside the band (no numeric constraint is encoded
    into its function-calling schema — see ``MatchResult.score``); we would rather
    cap a near-perfect match than discard it. Shared by ``match_profile`` and the
    sourcing pre-screen.
    """
    return max(0, min(100, score))


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


def _clean_domain(url: str | None) -> str | None:
    """Reduce any URL or bare host to its clean registrable host, or ``None``.

    Strips the scheme (``http``/``https``), ``www.``, path, and query string,
    so ``"https://www.gini-apps.com/careers?ref=x"`` -> ``"gini-apps.com"`` and a
    bare ``"gini-apps.com"`` passes through unchanged. Returns ``None`` for empty
    input or anything without a dot in the host.
    """
    if not url or not url.strip():
        return None
    raw = url.strip()
    # urlparse only populates ``hostname`` when a netloc is present, which needs a
    # scheme or a leading "//". Inputs like "www.foo.com/x" have neither, so add a
    # "//" to force netloc parsing (which then drops the path/query for us).
    if "://" not in raw:
        raw = "//" + raw
    host = (urlparse(raw).hostname or "").lower().removeprefix("www.")
    if not host or "." not in host:
        return None
    return host


def _employer_domain_from_url(source_url: str) -> str | None:
    """Extract the employer's own domain from a posting URL, or ``None``.

    Returns the bare host only when it is plausibly the employer's site. Job-board
    / ATS hosts (LinkedIn, Indeed, Greenhouse, …) are rejected — their domain is
    the board's, not the company's — so the caller falls back to another lookup
    key. Anything unparseable yields ``None``.
    """
    host = _clean_domain(source_url)
    if host is None:
        return None
    # Reject if the host *is* or is a subdomain of any known non-employer host.
    for board in _NON_EMPLOYER_HOSTS:
        if host == board or host.endswith("." + board):
            return None
    return host


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
        # Real infra/quota failure (not a genuinely empty posting): flag it so the
        # service doesn't persist a false REJECTED for a job we never scored.
        return {
            "extracted_requirements": ExtractedRequirements(),
            "analysis_failed": True,
        }

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
    """Score the candidate's OVERALL fit for the role via Gemini.

    Sends the full job posting, the extracted requirements (as a reference hint,
    not a checklist), and the full candidate profile to the model with structured
    output, returning a holistic fit score plus the strengths/gaps buckets for
    LangGraph to merge into the state. The judgment is deliberately lenient —
    transferable and implied skills count, and a few unmet requirements do not
    cap the score (see ``_SCORING_RUBRIC``). Any failure (API unavailable,
    invalid / empty model response) is logged and degrades to a zero score so the
    graph can still route safely to the end.
    """
    logger.info("node", extra={"node": "match_profile"})

    # Nothing to compare against -> a zero score, surfaced explicitly rather
    # than spending an API call that can only return 0.
    if not state.profile_text or not state.profile_text.strip():
        logger.warning("match_profile.empty_profile_text")
        return {"match_score": 0, "match_reasoning": "No profile provided."}
    reqs = state.extracted_requirements
    # Holistic scoring judges the full posting against the full profile, so the
    # extracted requirements are only a hint. Bail only when there is nothing at
    # all to evaluate the role from (no requirements AND no posting text).
    if reqs.is_empty() and not (state.job_text and state.job_text.strip()):
        logger.warning("match_profile.no_job_data")
        return {"match_score": 0, "match_reasoning": "No job data to evaluate."}

    # Extracted requirements are passed as a tagged *reference* (criticality
    # labels), NOT a checklist — the score is an overall judgment of the whole
    # profile against the whole posting (which is included in full below).
    requirements_block = reqs.to_prompt_block()
    human_content = (
        f"JOB POSTING:\n{state.job_text}\n\n"
        f"KEY REQUIREMENTS (extracted, reference only — not a checklist):\n"
        f"{requirements_block}\n\n"
        f"CANDIDATE PROFILE (full):\n{state.profile_text}"
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
        # Infra/quota failure: flag it so a transient error is not persisted as a
        # genuine REJECTED verdict (the job stays NEW and can be retried).
        return {
            "match_score": 0,
            "match_reasoning": "Error during LLM evaluation.",
            "analysis_failed": True,
        }

    if result is None:
        logger.warning("match_profile.no_structured_output")
        return {
            "match_score": 0,
            "match_reasoning": "LLM returned no structured output.",
        }

    score = _clamp_score(result.score)
    logger.info("match_profile.done", extra={"score": score})
    return {
        "match_score": score,
        "matching_skills": result.matching_skills,
        "missing_skills": result.missing_skills,
        "match_reasoning": result.reasoning,
    }


async def find_recruiter_contact(state: GraphState) -> dict:
    """Resolve a named recruiter / hiring manager for the posting via Hunter.io.

    Runs right before ``generate_cover_letter`` so the letter can be addressed to
    a real person. The employer domain is resolved by precedence, most accurate
    first: ``company_website`` (the employer's own site, from Apify) -> a real
    employer domain parsed out of ``source_url`` (rare here — the sourcing
    pipeline is LinkedIn-based, whose URLs are never the employer's) -> the
    ``company_name``, which Hunter resolves server-side. The first returned
    contact is the most relevant.

    Fail-soft by design: Hunter already degrades any error to an empty list, and
    this node additionally guards against a missing key/identifier and never
    raises. When no named contact is found, ``recruiter_name`` / ``recruiter_email``
    stay ``None`` and the cover letter falls back to a generic greeting.
    """
    logger.info("node", extra={"node": "find_recruiter_contact"})

    # Prefer the employer's own website domain; fall back to a non-board domain in
    # the source URL; the company name is the last resort (Hunter resolves it).
    domain = _clean_domain(state.company_website) or _employer_domain_from_url(
        state.source_url
    )
    company = state.company_name.strip() or None
    # Log which identifier we resolved (and from which input) BEFORE the call, so
    # the cause of a generic greeting is visible even if the request then fails.
    logger.info(
        "find_recruiter_contact.lookup",
        extra={
            "domain": domain,
            "company": company,
            "company_website": state.company_website,
            "source_url": state.source_url,
        },
    )
    if not domain and not company:
        logger.warning("find_recruiter_contact.no_identifier")
        return {"recruiter_name": None, "recruiter_email": None}

    try:
        contacts = await HunterClient().search_hiring_managers(
            domain, company=company
        )
    except Exception:  # noqa: BLE001 — node must never crash the graph
        logger.exception("find_recruiter_contact.failed")
        return {"recruiter_name": None, "recruiter_email": None}

    if not contacts:
        logger.warning(
            "find_recruiter_contact.none_found",
            extra={"domain": domain, "company": company},
        )
        return {"recruiter_name": None, "recruiter_email": None}

    # The list is already filtered to personal, named contacts; take the first
    # (Hunter orders by relevance / confidence) and use its first name for the
    # salutation. Last name is appended when present for a fuller greeting.
    top = contacts[0]
    recruiter_name = " ".join(
        part for part in (top.first_name, top.last_name) if part
    ).strip() or None
    logger.info(
        "find_recruiter_contact.found",
        extra={
            "recruiter_name": recruiter_name,
            "recruiter_email": top.email,
            "position": top.position,
            "candidate_count": len(contacts),
        },
    )
    return {"recruiter_name": recruiter_name, "recruiter_email": top.email}


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

    # Every early/error path flags the failure WITHOUT overwriting any prior draft
    # (so a failed revision keeps the earlier good letter). On the first pass there
    # is no prior draft, so ``cover_letter_draft`` simply stays None — the reviewer
    # then skips and ``should_revise`` ends, instead of looping a failing drafter.
    def _fallback() -> dict:
        return {"drafting_failed": True}

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
    requirements_block = reqs.to_prompt_block()
    human_content = (
        f"JOB POSTING:\n{state.job_text}\n\n"
        f"EXTRACTED REQUIREMENTS:\n{requirements_block}\n\n"
        f"CANDIDATE PROFILE:\n{state.profile_text}"
    )

    # Address the letter to the recruiter ``find_recruiter_contact`` resolved, if
    # any. Only the first name is needed for the salutation; absence of this line
    # is the model's cue to fall back to the generic 'Dear Hiring Team' greeting.
    if state.recruiter_name:
        human_content += f"\n\nRECIPIENT NAME: {state.recruiter_name}"

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
    return {"cover_letter_draft": result.cover_letter, "drafting_failed": False}


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
    requirements_block = reqs.to_prompt_block()
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

    # Review is opt-in: when disabled (the default) skip it entirely — no LLM call,
    # no revision loop — to conserve the free-tier quota. ``should_revise`` then
    # ends the graph since there are no comments.
    if not get_ai_settings().ai_enable_review:
        logger.info("reviewer.disabled")
        return {"review_comments": []}

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
    requirements_block = reqs.to_prompt_block()
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
    in parallel (returning the targets as a list is how LangGraph triggers a
    parallel fan-out from a conditional edge): the tailored CV is drafted
    directly, while the cover-letter branch first runs ``find_recruiter_contact``
    so the letter can be addressed to a named recruiter.
    """
    if state.match_score < state.score_threshold:
        logger.info(
            "should_draft.skip",
            extra={"score": state.match_score, "threshold": state.score_threshold},
        )
        return "__end__"
    return ["find_recruiter_contact", "generate_tailored_cv"]


def should_revise(state: GraphState) -> str:
    """Decide whether to loop back for another draft or finish.

    Loop back to ``generate_cover_letter`` while there are outstanding review
    comments (non-empty after stripping) and we are under the revision cap;
    otherwise terminate the graph. The CV branch is never revised — only the
    cover letter is fact-checked by the reviewer.
    """
    # If the last drafting attempt failed (LLM error / quota), there is nothing to
    # revise — looping would just burn more failing calls (and minutes of latency).
    if state.drafting_failed:
        return "__end__"
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

    score = _clamp_score(result.score)
    return {"score": score, "reason": result.reason}
