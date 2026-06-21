# Implementation Summary (historical)

> **Superseded.** This file originally documented the first integration of the
> LangGraph match endpoint into FastAPI. That work has since been extended
> substantially (parallel CV ∥ Hunter branches, WebSocket streaming, sourcing
> pre-screen, Gmail outreach, soft-delete, applied marker).
>
> For current, code-accurate documentation use:
> - [ARCHITECTURE.md](ARCHITECTURE.md) — end-to-end runtime flow
> - [CHANGELOG.md](CHANGELOG.md) — detailed change history
> - [docs/AI_Layer_Spec.md](docs/AI_Layer_Spec.md) — LangGraph pipeline
> - [docs/API_Contracts.md](docs/API_Contracts.md) — endpoints
>
> Notes that are now **out of date** in the original text (kept here only as
> history): the WebSocket streaming once listed under "Next Steps" is implemented;
> the `score_threshold` default is **50** (in `GraphState`), not 70; result saving
> now persists `tailored_cv_draft`, `match_reason`, `recruiter_name`/`recruiter_email`
> in addition to `cover_letter_draft`.

The one design decision still worth restating, because it remains a binding
invariant: **the service layer only `flush`es; the request owns the
`commit`** (Unit of Work). See [CLAUDE.md](CLAUDE.md).
