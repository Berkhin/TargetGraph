"""Email permutation engine.

Turns ``(first, last, domain)`` into an ordered list of likely addresses.
Order matters: probing stops at the first deliverable hit, so the most common
corporate conventions are emitted first to minimise SMTP round-trips.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable

from app.services.email_verification.models import EmailCandidate

# A pattern builder takes (first, last, first_initial, last_initial) -> local-part.
_Builder = Callable[[str, str, str, str], str]

# Patterns ordered by empirical prevalence in corporate mail systems.
# Each entry maps a stable id -> a builder over normalised name parts.
# ``fi``/``li`` are the first letters of first/last name.
_PATTERN_BUILDERS: tuple[tuple[str, _Builder], ...] = (
    ("first.last", lambda f, l, fi, li: f"{f}.{l}"),
    ("first", lambda f, l, fi, li: f),
    ("flast", lambda f, l, fi, li: f"{fi}{l}"),
    ("first_last", lambda f, l, fi, li: f"{f}_{l}"),
    ("firstlast", lambda f, l, fi, li: f"{f}{l}"),
    ("f.last", lambda f, l, fi, li: f"{fi}.{l}"),
    ("lastf", lambda f, l, fi, li: f"{l}{fi}"),
    ("last.first", lambda f, l, fi, li: f"{l}.{f}"),
    ("last", lambda f, l, fi, li: l),
    ("firstl", lambda f, l, fi, li: f"{f}{li}"),
    ("first-last", lambda f, l, fi, li: f"{f}-{l}"),
    ("fi.li", lambda f, l, fi, li: f"{fi}.{li}"),
)


def _normalise_part(value: str) -> str:
    """Lower-case, strip accents, and keep only ``[a-z0-9]``.

    ``"Müller"`` -> ``"muller"``, ``"O'Brien"`` -> ``"obrien"``. This mirrors how
    most mail systems mint local-parts and avoids minting invalid addresses.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in ascii_only.lower() if ch.isalnum())


def generate_candidates(
    first_name: str,
    last_name: str,
    domain: str,
    *,
    limit: int | None = None,
) -> list[EmailCandidate]:
    """Generate de-duplicated, ordered email candidates for the person.

    Args:
        first_name: Raw first name (may contain accents / punctuation).
        last_name: Raw last name.
        domain: Already-normalised company domain (see the request model).
        limit: Optional cap on the number of candidates returned.

    Returns:
        Ordered, unique candidates. Empty if names normalise to nothing.
    """
    first = _normalise_part(first_name)
    last = _normalise_part(last_name)
    if not first or not last:
        return []

    fi, li = first[0], last[0]

    seen_locals: set[str] = set()
    candidates: list[EmailCandidate] = []
    for pattern_id, build in _PATTERN_BUILDERS:
        local_part = build(first, last, fi, li)
        if not local_part or local_part in seen_locals:
            continue
        seen_locals.add(local_part)
        candidates.append(
            EmailCandidate(email=f"{local_part}@{domain}", pattern=pattern_id)
        )
        if limit is not None and len(candidates) >= limit:
            break

    return candidates
