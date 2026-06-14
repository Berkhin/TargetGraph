"""Unit tests for the permutation engine (pure logic, no I/O)."""

from __future__ import annotations

from app.services.email_verification.permutations import generate_candidates


def test_most_common_pattern_is_first() -> None:
    candidates = generate_candidates("Alex", "Mercer", "company.com")
    assert candidates[0].email == "alex.mercer@company.com"
    assert candidates[0].pattern == "first.last"


def test_candidates_are_unique_and_well_formed() -> None:
    candidates = generate_candidates("Alex", "Mercer", "company.com")
    emails = [c.email for c in candidates]
    assert len(emails) == len(set(emails))
    assert all(e.endswith("@company.com") for e in emails)


def test_accents_and_punctuation_are_normalised() -> None:
    candidates = generate_candidates("Renée", "O'Brien", "acme.io")
    locals_ = {c.email.split("@", 1)[0] for c in candidates}
    assert "renee.obrien" in locals_
    # No non-ascii or punctuation leaked into any local-part.
    assert all(local.replace(".", "").replace("_", "").replace("-", "").isalnum()
               for local in locals_)


def test_limit_is_respected() -> None:
    candidates = generate_candidates("Alex", "Mercer", "company.com", limit=3)
    assert len(candidates) == 3


def test_empty_after_normalisation_returns_nothing() -> None:
    # Names that normalise to empty (e.g. only punctuation) yield no candidates.
    assert generate_candidates("'", "!!", "company.com") == []
