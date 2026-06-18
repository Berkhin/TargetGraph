"""Tests for the new AI building blocks: the sourcing pre-screen, the tailored-CV
node, and the parallel graph topology.

No Gemini call is made — the cached structured-output chains are swapped for a
deterministic fake whose ``ainvoke`` returns a canned result (or raises).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.ai import nodes
from app.ai.nodes import (
    GeneratedDocuments,
    MatchResult,
    RelevanceResult,
    ReviewResult,
    extract_requirements,
    evaluate_job_relevance,
    find_recruiter_contact,
    generate_cover_letter,
    generate_tailored_cv,
    match_profile,
    reviewer,
    should_draft,
    should_revise,
)
from app.ai.orchestrator import compiled_graph, workflow
from app.ai.state import ExtractedRequirements, GraphState, TailoredCV
from app.models.schemas.hunter import HunterContact


class _FakeChain:
    """Stand-in for a ``with_structured_output`` chain."""

    def __init__(self, result: Any = None, *, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    async def ainvoke(self, messages: Any) -> Any:
        if self._error is not None:
            raise self._error
        return self._result


def _state(job_text: str = "Build async APIs", profile_text: str = "# Ada") -> GraphState:
    return GraphState(job_text=job_text, profile_text=profile_text)


# --------------------------------------------------------------------------- #
# evaluate_job_relevance                                                       #
# --------------------------------------------------------------------------- #
async def test_evaluate_job_relevance_clamps_score(monkeypatch) -> None:
    monkeypatch.setattr(
        nodes,
        "_get_relevance_chain",
        lambda: _FakeChain(RelevanceResult(score=140, reason="great")),
    )
    out = await evaluate_job_relevance("a real job", "a real profile")
    assert out == {"score": 100, "reason": "great"}


async def test_evaluate_job_relevance_fail_open_on_error(monkeypatch) -> None:
    monkeypatch.setattr(
        nodes,
        "_get_relevance_chain",
        lambda: _FakeChain(error=RuntimeError("gemini down")),
    )
    out = await evaluate_job_relevance("a real job", "a real profile")
    assert out["score"] is None  # fail-open: caller keeps the job NEW


async def test_evaluate_job_relevance_empty_inputs_skip_llm(monkeypatch) -> None:
    def _boom() -> _FakeChain:  # must not be called
        raise AssertionError("chain built for empty input")

    monkeypatch.setattr(nodes, "_get_relevance_chain", _boom)
    assert (await evaluate_job_relevance("", "profile"))["score"] is None
    assert (await evaluate_job_relevance("job", ""))["score"] is None


# --------------------------------------------------------------------------- #
# generate_tailored_cv                                                         #
# --------------------------------------------------------------------------- #
async def test_generate_tailored_cv_returns_markdown(monkeypatch) -> None:
    monkeypatch.setattr(
        nodes,
        "_get_tailored_cv_chain",
        lambda: _FakeChain(TailoredCV(tailored_cv="# Ada\n- Built APIs")),
    )
    out = await generate_tailored_cv(_state())
    assert out == {"tailored_cv": "# Ada\n- Built APIs"}


async def test_generate_tailored_cv_degrades_to_none_on_error(monkeypatch) -> None:
    monkeypatch.setattr(
        nodes,
        "_get_tailored_cv_chain",
        lambda: _FakeChain(error=RuntimeError("boom")),
    )
    out = await generate_tailored_cv(_state())
    assert out == {"tailored_cv": None}


async def test_generate_tailored_cv_guards_empty_profile(monkeypatch) -> None:
    def _boom() -> _FakeChain:
        raise AssertionError("chain built without grounding")

    monkeypatch.setattr(nodes, "_get_tailored_cv_chain", _boom)
    out = await generate_tailored_cv(_state(profile_text="  "))
    assert out == {"tailored_cv": None}


# --------------------------------------------------------------------------- #
# Graph topology                                                               #
# --------------------------------------------------------------------------- #
def test_graph_has_parallel_drafting_nodes() -> None:
    names = set(workflow.nodes)
    assert {"generate_cover_letter", "generate_tailored_cv"} <= names
    assert "draft_documents" not in names  # old single node is gone


async def test_generate_cover_letter_failure_flags_without_overwriting(monkeypatch) -> None:
    # On failure the node must flag drafting_failed and NOT emit a cover_letter_draft
    # key (so a prior good draft survives, and the first pass simply stays None).
    monkeypatch.setattr(
        nodes,
        "_get_draft_chain",
        lambda: _FakeChain(error=RuntimeError("quota")),
    )
    out = await generate_cover_letter(_state())
    assert out == {"drafting_failed": True}
    assert "cover_letter_draft" not in out


async def test_extract_requirements_flags_analysis_failed_on_error(monkeypatch) -> None:
    monkeypatch.setattr(
        nodes, "_get_extraction_chain", lambda: _FakeChain(error=RuntimeError("quota"))
    )
    out = await extract_requirements(_state(job_text="Real job posting"))
    assert out["analysis_failed"] is True


async def test_match_profile_flags_analysis_failed_on_error(monkeypatch) -> None:
    monkeypatch.setattr(
        nodes, "_get_match_chain", lambda: _FakeChain(error=RuntimeError("quota"))
    )
    state = GraphState(
        job_text="j",
        profile_text="p",
        extracted_requirements=ExtractedRequirements(hard_skills=["Python"]),
    )
    out = await match_profile(state)
    assert out["analysis_failed"] is True
    assert out["match_score"] == 0


class _Settings:
    def __init__(self, enable_review: bool) -> None:
        self.ai_enable_review = enable_review


async def test_reviewer_disabled_skips_llm(monkeypatch) -> None:
    # With review off (default), the reviewer must return no comments WITHOUT
    # building/calling the review chain (zero LLM cost).
    monkeypatch.setattr(nodes, "get_ai_settings", lambda: _Settings(False))

    def _boom():
        raise AssertionError("review chain built while review disabled")

    monkeypatch.setattr(nodes, "_get_review_chain", _boom)
    state = GraphState(
        job_text="j", profile_text="p", cover_letter_draft="Dear team,"
    )
    out = await reviewer(state)
    assert out == {"review_comments": []}


async def test_reviewer_enabled_runs_chain(monkeypatch) -> None:
    monkeypatch.setattr(nodes, "get_ai_settings", lambda: _Settings(True))
    monkeypatch.setattr(
        nodes,
        "_get_review_chain",
        lambda: _FakeChain(ReviewResult(is_approved=True, comments=[])),
    )
    state = GraphState(
        job_text="j", profile_text="p", cover_letter_draft="Dear team,"
    )
    out = await reviewer(state)
    assert "review_comments" in out


def test_should_revise_stops_when_drafting_failed() -> None:
    # Even with outstanding review comments, a failed drafter must not be looped.
    state = GraphState(
        job_text="j",
        profile_text="p",
        drafting_failed=True,
        review_comments=["fix this"],
        revision_number=0,
    )
    assert should_revise(state) == "__end__"


def test_should_draft_skips_below_threshold() -> None:
    state = GraphState(
        job_text="j", profile_text="p", match_score=50, score_threshold=70
    )
    assert should_draft(state) == "__end__"


def test_should_draft_fans_out_at_threshold() -> None:
    state = GraphState(
        job_text="j", profile_text="p", match_score=70, score_threshold=70
    )
    # The cover-letter branch fans out via find_recruiter_contact (recruiter
    # lookup runs before drafting); the tailored CV is drafted directly.
    assert should_draft(state) == ["find_recruiter_contact", "generate_tailored_cv"]


async def test_compiled_graph_skips_drafting_below_threshold(monkeypatch) -> None:
    # A sub-threshold score must short-circuit to END right after match_profile:
    # no cover letter, no CV, and crucially the drafting/review chains are never
    # built (= no LLM calls spent on a job that will be rejected anyway).
    monkeypatch.setattr(
        nodes,
        "_get_extraction_chain",
        lambda: _FakeChain(ExtractedRequirements(hard_skills=["Rust"])),
    )
    monkeypatch.setattr(
        nodes,
        "_get_match_chain",
        lambda: _FakeChain(MatchResult(score=40, reasoning="missing hard skills")),
    )

    def _must_not_run() -> _FakeChain:
        raise AssertionError("drafting chain built for a sub-threshold match")

    monkeypatch.setattr(nodes, "_get_draft_chain", _must_not_run)
    monkeypatch.setattr(nodes, "_get_tailored_cv_chain", _must_not_run)
    monkeypatch.setattr(nodes, "_get_review_chain", _must_not_run)

    result = await compiled_graph.ainvoke(
        {"job_text": "Rust role", "profile_text": "# Ada\n- Python", "score_threshold": 70}
    )

    assert result["match_score"] == 40
    assert result.get("cover_letter_draft") is None
    assert result.get("tailored_cv") is None


# --------------------------------------------------------------------------- #
# find_recruiter_contact (Hunter.io cold-outreach lookup)                      #
# --------------------------------------------------------------------------- #
class _FakeHunterClient:
    """Stand-in for HunterClient: records the call and returns canned contacts."""

    calls: list[dict] = []

    def __init__(self, *, contacts: list[HunterContact]) -> None:
        self._contacts = contacts

    async def search_hiring_managers(self, domain=None, *, company=None, **kw):
        type(self).calls.append({"domain": domain, "company": company})
        return self._contacts


def _patch_hunter(monkeypatch, contacts: list[HunterContact]) -> None:
    _FakeHunterClient.calls = []
    monkeypatch.setattr(
        nodes, "HunterClient", lambda: _FakeHunterClient(contacts=contacts)
    )


async def test_find_recruiter_contact_takes_first_contact(monkeypatch) -> None:
    _patch_hunter(
        monkeypatch,
        [
            HunterContact(
                email="ana@acme.com", first_name="Ana", last_name="Lee",
                position="Recruiter", confidence=88,
            ),
            HunterContact(email="bob@acme.com", first_name="Bob"),
        ],
    )
    out = await find_recruiter_contact(
        GraphState(job_text="j", profile_text="p", company_name="Acme")
    )
    assert out == {"recruiter_name": "Ana Lee", "recruiter_email": "ana@acme.com"}
    # LinkedIn-style pipeline: no employer domain, so the company name is used.
    assert _FakeHunterClient.calls == [{"domain": None, "company": "Acme"}]


async def test_find_recruiter_contact_prefers_company_website(monkeypatch) -> None:
    _patch_hunter(
        monkeypatch, [HunterContact(email="ana@gini-apps.com", first_name="Ana")]
    )
    await find_recruiter_contact(
        GraphState(
            job_text="j", profile_text="p", company_name="Gini Apps",
            # A real LinkedIn source_url is ignored in favour of the website, and
            # the website is cleaned of scheme/www/path/query.
            source_url="https://www.linkedin.com/jobs/view/1",
            company_website="https://www.gini-apps.com/careers?ref=x",
        )
    )
    assert _FakeHunterClient.calls == [
        {"domain": "gini-apps.com", "company": "Gini Apps"}
    ]


async def test_find_recruiter_contact_prefers_employer_domain(monkeypatch) -> None:
    _patch_hunter(
        monkeypatch, [HunterContact(email="ana@acme.com", first_name="Ana")]
    )
    await find_recruiter_contact(
        GraphState(
            job_text="j", profile_text="p", company_name="Acme",
            source_url="https://careers.acme.com/jobs/1",
        )
    )
    # A real employer domain in the URL is passed through (company also supplied).
    assert _FakeHunterClient.calls == [
        {"domain": "careers.acme.com", "company": "Acme"}
    ]


async def test_find_recruiter_contact_none_found_leaves_fields_empty(monkeypatch) -> None:
    _patch_hunter(monkeypatch, [])
    out = await find_recruiter_contact(
        GraphState(job_text="j", profile_text="p", company_name="Acme")
    )
    assert out == {"recruiter_name": None, "recruiter_email": None}


async def test_find_recruiter_contact_skips_lookup_without_identifier(monkeypatch) -> None:
    def _boom():
        raise AssertionError("HunterClient built without a company/domain")

    monkeypatch.setattr(nodes, "HunterClient", _boom)
    out = await find_recruiter_contact(GraphState(job_text="j", profile_text="p"))
    assert out == {"recruiter_name": None, "recruiter_email": None}


class _CapturingChain:
    """Fake chain that records the HumanMessage content it was invoked with."""

    last_human: str = ""

    async def ainvoke(self, messages):
        type(self).last_human = messages[-1].content
        return GeneratedDocuments(cover_letter="Dear Ana, ...")


async def test_generate_cover_letter_passes_recipient_name(monkeypatch) -> None:
    monkeypatch.setattr(nodes, "_get_draft_chain", lambda: _CapturingChain())
    await generate_cover_letter(
        GraphState(job_text="j", profile_text="p", recruiter_name="Ana Lee")
    )
    assert "RECIPIENT NAME: Ana Lee" in _CapturingChain.last_human


async def test_generate_cover_letter_omits_recipient_when_unknown(monkeypatch) -> None:
    monkeypatch.setattr(nodes, "_get_draft_chain", lambda: _CapturingChain())
    await generate_cover_letter(GraphState(job_text="j", profile_text="p"))
    assert "RECIPIENT NAME" not in _CapturingChain.last_human


async def test_compiled_graph_runs_parallel_branches_to_completion(monkeypatch) -> None:
    # End-to-end topology check: the fan-out to the two drafting nodes and the
    # fan-in to the reviewer must execute without deadlock and populate BOTH
    # cover_letter_draft and tailored_cv. All chains are stubbed (no Gemini).
    monkeypatch.setattr(
        nodes,
        "_get_extraction_chain",
        lambda: _FakeChain(ExtractedRequirements(hard_skills=["Python"])),
    )
    monkeypatch.setattr(
        nodes,
        "_get_match_chain",
        lambda: _FakeChain(MatchResult(score=90, reasoning="strong")),
    )
    monkeypatch.setattr(
        nodes,
        "_get_draft_chain",
        lambda: _FakeChain(GeneratedDocuments(cover_letter="Dear team,")),
    )
    monkeypatch.setattr(
        nodes,
        "_get_tailored_cv_chain",
        lambda: _FakeChain(TailoredCV(tailored_cv="# CV\n- Python")),
    )
    # Reviewer approves immediately so the revision loop does not fire.
    monkeypatch.setattr(
        nodes,
        "_get_review_chain",
        lambda: _FakeChain(ReviewResult(is_approved=True, comments=[])),
    )

    result = await compiled_graph.ainvoke(
        {"job_text": "Python role", "profile_text": "# Ada\n- Python"}
    )

    assert result["match_score"] == 90
    assert result["cover_letter_draft"] == "Dear team,"
    assert result["tailored_cv"] == "# CV\n- Python"
