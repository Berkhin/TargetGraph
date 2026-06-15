r"""LangGraph orchestrator: wires the matching-pipeline nodes into a graph.

Topology::

    START -> extract_requirements -> match_profile -> draft_documents
          -> reviewer --(should_revise)--> draft_documents  (loop, max 3)
                                       \--> END

The conditional edge from ``reviewer`` sends the state back to
``draft_documents`` while reviews remain (bounded by the revision cap inside
:func:`should_revise`), otherwise it ends the run.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.ai.nodes import (
    draft_documents,
    extract_requirements,
    match_profile,
    reviewer,
    should_revise,
)
from app.ai.state import GraphState

workflow = StateGraph(GraphState)

# --- Nodes ---
workflow.add_node("extract_requirements", extract_requirements)
workflow.add_node("match_profile", match_profile)
workflow.add_node("draft_documents", draft_documents)
workflow.add_node("reviewer", reviewer)

# --- Linear edges ---
workflow.add_edge(START, "extract_requirements")
workflow.add_edge("extract_requirements", "match_profile")
workflow.add_edge("match_profile", "draft_documents")
workflow.add_edge("draft_documents", "reviewer")

# --- Conditional edge: revise loop or finish ---
workflow.add_conditional_edges(
    "reviewer",
    should_revise,
    {
        "draft_documents": "draft_documents",  # Key = return value from should_revise
        "__end__": END,                         # Key = return value "__end__" -> END constant
    },
)

compiled_graph = workflow.compile()
