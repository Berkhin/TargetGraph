r"""LangGraph orchestrator: wires the matching-pipeline nodes into a graph.

Topology::

    START -> extract_requirements -> match_profile
                                          |
                              (should_draft: score gate)
                            below threshold |  at/above threshold
                                    |        +-------------+-------------+
                                    v        v                           v
                                   END  generate_cover_letter   generate_tailored_cv
                                             |                           |
                                             +-------------+-------------+
                                                           v
                                                        reviewer
                          --(should_revise)--> generate_cover_letter  (loop, max 3)
                                          \--> END

After ``match_profile`` a score gate (:func:`should_draft`) decides whether to
draft at all: a job scoring below ``score_threshold`` will be rejected anyway, so
the graph short-circuits to END without spending any drafting LLM calls. At/above
the threshold it fans out — the cover letter and the ATS-tailored CV are drafted
in parallel (they write disjoint state keys, so no reducer is needed). Both fan
back into ``reviewer``, which fact-checks the cover letter only. The conditional
edge from ``reviewer`` loops back to ``generate_cover_letter`` while reviews
remain (bounded by the revision cap in :func:`should_revise`); on a revision pass
only the cover-letter node re-fires, so the CV is not regenerated.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.ai.nodes import (
    extract_requirements,
    generate_cover_letter,
    generate_tailored_cv,
    match_profile,
    reviewer,
    should_draft,
    should_revise,
)
from app.ai.state import GraphState

workflow = StateGraph(GraphState)

# --- Nodes ---
workflow.add_node("extract_requirements", extract_requirements)
workflow.add_node("match_profile", match_profile)
workflow.add_node("generate_cover_letter", generate_cover_letter)
workflow.add_node("generate_tailored_cv", generate_tailored_cv)
workflow.add_node("reviewer", reviewer)

# --- Linear edges up to the score gate ---
workflow.add_edge(START, "extract_requirements")
workflow.add_edge("extract_requirements", "match_profile")

# --- Score gate: skip drafting (straight to END) for sub-threshold matches,
#     otherwise fan out to draft the cover letter and tailored CV in parallel. ---
workflow.add_conditional_edges(
    "match_profile",
    should_draft,
    {
        "generate_cover_letter": "generate_cover_letter",
        "generate_tailored_cv": "generate_tailored_cv",
        "__end__": END,
    },
)

# --- Fan-in: reviewer waits for both branches ---
workflow.add_edge("generate_cover_letter", "reviewer")
workflow.add_edge("generate_tailored_cv", "reviewer")

# --- Conditional edge: revise the cover letter or finish ---
workflow.add_conditional_edges(
    "reviewer",
    should_revise,
    {
        "generate_cover_letter": "generate_cover_letter",  # Key = should_revise return
        "__end__": END,                                     # Key "__end__" -> END constant
    },
)

compiled_graph = workflow.compile()
