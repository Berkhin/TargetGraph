"""Render domain DTOs into LLM-friendly Markdown.

The matching graph consumes plain text, not structured objects: nodes are
prompted with ``profile_text`` and reason over it directly. These helpers flatten
a :class:`~app.models.schemas.profile.ProfileRead` aggregate into a single
Markdown document the LLM can read top-to-bottom — headings for structure,
bullet lists for enumerable detail.
"""

from __future__ import annotations

import datetime
from typing import Any

from app.models.schemas.profile import ExperienceRead, ProfileRead

# Keys in ``ProfileRead.preferences`` that read as contact details rather than
# job-search preferences. Surfaced first, in this order, so the LLM sees how to
# reach the candidate before the softer preference signals.
_CONTACT_KEYS: tuple[str, ...] = (
    "email",
    "phone",
    "location",
    "linkedin",
    "github",
    "website",
    "portfolio",
)


def _format_period(start: datetime.date, end: datetime.date | None) -> str:
    """Render an experience date span as ``YYYY-MM – YYYY-MM`` (open → Present)."""
    start_label = start.strftime("%Y-%m")
    end_label = end.strftime("%Y-%m") if end is not None else "Present"
    return f"{start_label} – {end_label}"


def _render_value(value: Any) -> str:
    """Render a free-form preference/contact value as flat text for the LLM.

    ``preferences`` is typed ``dict[str, Any]``, so a value may be a list or a
    nested mapping. Flatten sequences into a comma-joined string rather than
    leaking a Python ``repr`` (``['x', 'y']``) into the prompt; scalars and
    mappings fall back to ``str``.
    """
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return str(value)


def _format_experience(exp: ExperienceRead) -> list[str]:
    """Render one work-history entry as a block of Markdown lines."""
    lines = [
        f"### {exp.role} @ {exp.company}",
        f"*{_format_period(exp.start_date, exp.end_date)}*",
    ]
    if exp.highlights:
        # Blank line so the bullets render as a list (strict parsers require a
        # paragraph break before a list).
        lines.append("")
        lines.extend(f"- {highlight}" for highlight in exp.highlights)
    return lines


def format_profile_to_markdown(profile: ProfileRead) -> str:
    """Flatten a full profile aggregate into a single Markdown document.

    Sections are emitted only when they carry content, so an LLM is never asked
    to reason about empty headings. The output is deterministic — repository
    order is preserved — which keeps prompt caching and test snapshots stable.

    Args:
        profile: The eagerly-loaded profile, including experiences and skills.

    Returns:
        A Markdown string covering identity, contacts, target titles, remaining
        preferences, experience and skills.
    """
    lines: list[str] = [f"# {profile.candidate_name}"]

    if profile.target_titles:
        lines += ["", f"**Target roles:** {', '.join(profile.target_titles)}"]

    # --- Contacts (pulled out of the free-form preferences bag) --------------
    preferences = dict(profile.preferences)
    # Pop every contact key out of preferences (even empty ones, so they never
    # resurface as blank lines under Preferences); keep only the truthy ones.
    contacts = [
        (key, value)
        for key in _CONTACT_KEYS
        if (value := preferences.pop(key, None))
    ]
    if contacts:
        lines += ["", "## Contacts"]
        lines += [
            f"- **{key.capitalize()}:** {_render_value(value)}" for key, value in contacts
        ]

    # --- Whatever is left is a genuine job-search preference -----------------
    # Skip blank values (None / "") so the LLM isn't fed empty keys, but keep
    # meaningful falsy ones like ``False`` / ``0``.
    prefs = [(k, v) for k, v in preferences.items() if v not in (None, "")]
    if prefs:
        lines += ["", "## Preferences"]
        lines += [f"- **{key}:** {_render_value(value)}" for key, value in prefs]

    # --- Experience ----------------------------------------------------------
    if profile.experiences:
        lines += ["", "## Experience"]
        for exp in profile.experiences:
            lines += ["", *_format_experience(exp)]

    # --- Skills --------------------------------------------------------------
    if profile.skills:
        lines += ["", "## Skills"]
        for group in profile.skills:
            skills = ", ".join(group.skills) if group.skills else "—"
            lines.append(f"- **{group.category}:** {skills}")

    return "\n".join(lines)
