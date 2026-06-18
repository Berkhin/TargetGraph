"""Cold-outreach email body composition.

Every recruiter email carries a fixed "Engineering Disclaimer" postscript that
explains the message was sent by this system and links to its source. Keeping the
wording here — a single pure function — means it lives in one place and is
unit-testable without touching the Gmail send path.
"""

from __future__ import annotations

# Sentinel marking an already-appended disclaimer. An operator may re-send a body
# that already carries the postscript (e.g. a previously composed draft); matching
# on this line keeps :func:`append_engineering_disclaimer` idempotent so the
# postscript never doubles up.
_DISCLAIMER_MARKER = "🚀 Engineering Disclaimer:"

_DISCLAIMER_TEMPLATE = (
    "🚀 Engineering Disclaimer:\n"
    "This email, along with the attached dynamically tailored PDF resume, was "
    "autonomously generated and delivered by a custom AI orchestration agent I "
    "engineered from scratch. The system utilizes an asynchronous Python/FastAPI "
    "backend, LangGraph for stateful LLM routing, and direct API integrations "
    "(Hunter.io & Gmail REST API via OAuth 2.0) to match my profile against your "
    "job description and reach out directly.\n\n"
    "You can review the architecture and source code here: {github_url}\n"
    "I'd love to bring this same level of automation, product-minded engineering, "
    "and complex problem-solving to your team."
)


def append_engineering_disclaimer(body: str, *, github_url: str) -> str:
    """Append the engineering-disclaimer postscript to an outreach body.

    Idempotent: if ``body`` already contains the disclaimer it is returned
    unchanged, so re-sending an edited message never duplicates the postscript.

    Args:
        body: The operator's message text.
        github_url: Repository URL advertised in the postscript.

    Returns:
        ``body`` with the disclaimer separated by a blank line, or ``body``
        unchanged when the disclaimer is already present.
    """
    if _DISCLAIMER_MARKER in body:
        return body
    disclaimer = _DISCLAIMER_TEMPLATE.format(github_url=github_url)
    return f"{body.rstrip()}\n\n{disclaimer}"
