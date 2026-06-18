"""Pydantic DTOs for the Hunter.io cold-outreach integration.

These mirror the subset of a Hunter ``domain-search`` email record we care
about for reaching a recruiter / hiring manager at a target company. Every
field is optional: Hunter routinely omits a contact's name, title, or LinkedIn
URL (generic role mailboxes like ``jobs@`` have no person attached), and a
partial contact is still useful, so we never reject a row on missing data.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HunterContact(BaseModel):
    """A single email record returned by Hunter's domain-search endpoint."""

    email: str | None = Field(default=None)
    first_name: str | None = Field(default=None)
    last_name: str | None = Field(default=None)
    # Job title, mapped from Hunter's ``position`` field.
    position: str | None = Field(default=None)
    linkedin_url: str | None = Field(default=None)
    # Hunter's 0-100 deliverability confidence for the address.
    confidence: int | None = Field(default=None, ge=0, le=100)
