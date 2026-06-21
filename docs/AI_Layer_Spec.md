# Component Specification: AI Orchestration (LangGraph)

The vacancy-processing pipeline is a compiled LangGraph `StateGraph`. This spec
describes its state, nodes, routing and models. For the high-level flow see
[../ARCHITECTURE.md](../ARCHITECTURE.md §3).

## 1. Architectural approach
* **Framework:** LangGraph (`StateGraph`), compiled to `compiled_graph`
  ([backend/app/ai/orchestrator.py](../backend/app/ai/orchestrator.py)).
* **State:** strict Pydantic model `GraphState`
  ([backend/app/ai/state.py](../backend/app/ai/state.py)) — every field typed with a
  default.
* **LLM integration:** `langchain-google-genai` (`ChatGoogleGenerativeAI`).
  Structured fields (score, requirements) use `.with_structured_output()`.
* **Config-driven models:** model id and temperature come from `AISettings`
  ([backend/app/core/config.py](../backend/app/core/config.py)) — never hard-coded.

## 2. GraphState — key fields

| Field | Type | Source | Purpose |
| --- | --- | --- | --- |
| `job_text`, `profile_text` | `str` | input | raw input for all nodes |
| `company_website` | `str \| None` | input (Apify) | employer domain for Hunter |
| `source_url`, `company_name` | `str` | input | Hunter fallbacks |
| `score_threshold` | `int = 50` | input | gate for `should_draft` |
| `match_score` | `int` | `match_profile` | 0–100 |
| `recruiter_name` / `recruiter_email` | `str \| None` | `find_recruiter_contact` | may be `None` (fail-soft) |
| `tailored_cv` | `str \| None` | `generate_tailored_cv` | ATS CV (Markdown) |
| `cover_letter_draft` | `str \| None` | `generate_cover_letter` | letter text |
| `review_comments` | `list[str]` | `reviewer` | empty = approved |
| `revision_number` | `int` | `reviewer` | cap = 3 |
| `analysis_failed` / `drafting_failed` | `bool` | nodes | error flags → stop, don't persist garbage |

> Naming: the runtime field is `tailored_cv`; the persisted DB column and the `done`
> WebSocket frame use `tailored_cv_draft`. Different layers, same content.

## 3. Nodes & routing

```
START → extract_requirements → match_profile → [should_draft]
   below threshold → END
   at/above        → ["find_recruiter_contact", "generate_tailored_cv"]   (PARALLEL)
        find_recruiter_contact → generate_cover_letter ─┐
        generate_tailored_cv ───────────────────────────┤
                                                    reviewer → [should_revise]
                                          comments && rev<3 → generate_cover_letter (loop)
                                          else              → END
```

1. **`extract_requirements`** — pulls key requirements from the raw job text.
2. **`match_profile`** — scores the profile against the requirements (0–100) with a
   reason; structured output.
3. **`should_draft` (router / score gate)** — `match_score >= score_threshold`
   returns the **list** `["find_recruiter_contact", "generate_tailored_cv"]`
   (LangGraph parallel fan-out); otherwise `"__end__"`.
4. **`find_recruiter_contact`** — Hunter.io lookup (see §5). **Fail-soft:** never
   crashes the graph; degrades to `recruiter_name/email = None`.
5. **`generate_tailored_cv`** — ATS CV in Markdown (low temperature, no fabrication).
6. **`generate_cover_letter`** — personalised letter; uses `recruiter_name` if
   present, else a *"Dear Hiring Team,"* fallback.
7. **`reviewer`** — strict fact-check (invented experience/skills only, not style).
   Writes `review_comments`.
8. **`should_revise` (router)** — non-empty comments **and** `revision_number < 3`
   → loop **only** `generate_cover_letter`; else `END`. The CV is generated once and
   reused; the Hunter lookup never repeats.

**Why no reducer:** the parallel branches write disjoint state keys (`tailored_cv`
vs `cover_letter_draft` / `recruiter_*`), so LangGraph merges them automatically.

## 4. Models per node

All Gemini via `langchain-google-genai`; defaults shown (override via env):

| Node | Model setting (default) | Temperature |
| --- | --- | --- |
| `extract_requirements`, `match_profile`, `reviewer`, `evaluate_job_relevance` | `GEMINI_MODEL` (`gemini-3.1-flash-lite`) | `0.0` |
| `generate_tailored_cv` | `GEMINI_GENERATION_MODEL` (`gemini-3.1-flash-lite`) | `0.3` |
| `generate_cover_letter` | `GEMINI_GENERATION_MODEL` (`gemini-3.1-flash-lite`) | `0.65` |

## 5. Recruiter contact (Hunter.io)

`find_recruiter_contact` ([backend/app/ai/nodes.py](../backend/app/ai/nodes.py))
selects the company identity by precision — `company_website` → employer domain
from `source_url` (job-board hosts rejected) → `company_name` — then calls
`HunterClient().search_hiring_managers(...)`. Only `type == "personal"` records
with a first name pass the `_is_personal_named` gate. Any error or empty result →
`None` (the graph still drafts a letter). This is the **only** contact-discovery
mechanism in the pipeline; the standalone SMTP verifier
([Email_Verification_Spec.md](./Email_Verification_Spec.md)) is not wired in here.

## 6. Pre-screening (sourcing-time gate)

`evaluate_job_relevance()` is a cheap, separate relevance check run during sourcing
(not part of the compiled graph). Score `< 55` → `FILTERED_OUT`; error/`None` →
`NEW` (**fail-open**). See [Sourcing_Spec.md](./Sourcing_Spec.md) and
[../ARCHITECTURE.md](../ARCHITECTURE.md §1).

## 7. Execution & streaming

The graph is driven by `run_pipeline` (REST) and `run_pipeline_stream` (WebSocket)
in [backend/app/services/orchestrator.py](../backend/app/services/orchestrator.py).
It holds **no DB connection** during the run. See
[Realtime_Matching_Spec.md](./Realtime_Matching_Spec.md).
