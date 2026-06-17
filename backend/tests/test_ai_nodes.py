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
    evaluate_job_relevance,
    generate_tailored_cv,
    should_draft,
)
from app.ai.orchestrator import compiled_graph, workflow
from app.ai.state import ExtractedRequirements, GraphState, TailoredCV


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


def test_should_draft_skips_below_threshold() -> None:
    state = GraphState(
        job_text="j", profile_text="p", match_score=50, score_threshold=70
    )
    assert should_draft(state) == "__end__"


def test_should_draft_fans_out_at_threshold() -> None:
    state = GraphState(
        job_text="j", profile_text="p", match_score=70, score_threshold=70
    )
    assert should_draft(state) == ["generate_cover_letter", "generate_tailored_cv"]


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
