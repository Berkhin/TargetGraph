"""Unit tests for the profile → Markdown formatter.

Pure functions over Pydantic DTOs — no DB or session needed. The output is
documented as deterministic, so the happy path is pinned with a full snapshot;
the rest cover the rendering edge cases (empty sections, contact extraction,
non-scalar preference values, open-ended date ranges).
"""

from __future__ import annotations

import datetime
import uuid

from app.models.schemas.profile import ProfileRead
from app.utils.formatters import format_profile_to_markdown


def _make_profile(**overrides: object) -> ProfileRead:
    """Build a ProfileRead with sensible defaults, overridable per test."""
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "candidate_name": "Jane Doe",
        "target_titles": [],
        "preferences": {},
        "experiences": [],
        "skills": [],
    }
    fields.update(overrides)
    return ProfileRead.model_validate(fields)


def test_full_profile_snapshot() -> None:
    """A fully-populated profile renders in the documented, stable layout."""
    profile = _make_profile(
        target_titles=["Senior AI Engineer", "Full Stack Engineer"],
        preferences={"email": "jane@x.io", "location": "Berlin", "remote": True},
        experiences=[
            {
                "id": uuid.uuid4(),
                "company": "Acme",
                "role": "Engineer",
                "highlights": ["Built X", "Shipped Y"],
                "start_date": datetime.date(2021, 3, 1),
                "end_date": None,
            }
        ],
        skills=[
            {
                "id": uuid.uuid4(),
                "category": "Languages",
                "skills": ["Python", "TypeScript"],
            }
        ],
    )

    expected = (
        "# Jane Doe\n"
        "\n"
        "**Target roles:** Senior AI Engineer, Full Stack Engineer\n"
        "\n"
        "## Contacts\n"
        "- **Email:** jane@x.io\n"
        "- **Location:** Berlin\n"
        "\n"
        "## Preferences\n"
        "- **remote:** True\n"
        "\n"
        "## Experience\n"
        "\n"
        "### Engineer @ Acme\n"
        "*2021-03 – Present*\n"
        "\n"
        "- Built X\n"
        "- Shipped Y\n"
        "\n"
        "## Skills\n"
        "- **Languages:** Python, TypeScript"
    )

    assert format_profile_to_markdown(profile) == expected


def test_minimal_profile_emits_only_name() -> None:
    """With no children/preferences, only the H1 heading is produced."""
    assert format_profile_to_markdown(_make_profile()) == "# Jane Doe"


def test_blank_and_empty_contacts_are_dropped() -> None:
    """Falsy contact values are excluded and never leak into Preferences."""
    out = format_profile_to_markdown(
        _make_profile(preferences={"email": "jane@x.io", "github": [], "phone": ""})
    )
    assert "Email" in out
    assert "github" not in out.lower()
    assert "phone" not in out.lower()


def test_list_preferences_are_flattened() -> None:
    """Non-scalar preference values render as comma-joined text, not a repr."""
    out = format_profile_to_markdown(
        _make_profile(preferences={"stack": ["Python", "Go"]})
    )
    assert "- **stack:** Python, Go" in out
    assert "['Python'" not in out


def test_meaningful_falsy_preferences_are_kept() -> None:
    """``False`` / ``0`` carry signal and are preserved; blanks are dropped."""
    out = format_profile_to_markdown(
        _make_profile(preferences={"remote": False, "note": ""})
    )
    assert "- **remote:** False" in out
    assert "note" not in out.lower()


def test_closed_date_range_is_rendered() -> None:
    """A finished role shows both endpoints rather than 'Present'."""
    out = format_profile_to_markdown(
        _make_profile(
            experiences=[
                {
                    "id": uuid.uuid4(),
                    "company": "Acme",
                    "role": "Engineer",
                    "highlights": [],
                    "start_date": datetime.date(2019, 1, 1),
                    "end_date": datetime.date(2021, 6, 1),
                }
            ]
        )
    )
    assert "*2019-01 – 2021-06*" in out
