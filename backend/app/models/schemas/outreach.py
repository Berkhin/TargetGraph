"""Pydantic DTOs for cold-outreach email sending (Gmail API).

Request/response shapes for ``POST /api/v1/jobs/{job_id}/outreach/send``, which
sends a one-off plain-text email (typically to a recruiter resolved earlier by
the Hunter.io lookup) through :class:`app.services.gmail_client.GmailClient`.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class OutreachSendRequest(BaseModel):
    """Body for sending a cold-outreach email."""

    # EmailStr (not bare str) so a malformed address is rejected with a 422 here
    # rather than failing deep inside the Gmail API call.
    to_email: EmailStr
    subject: str = Field(min_length=1, max_length=998)  # RFC 5322 header cap
    body: str = Field(min_length=1)
    # Optional file attachment (e.g. the tailored-CV PDF generated client-side).
    # The bytes are carried base64-encoded; both fields are set together or not
    # at all — only when both are present is an attachment added.
    attachment_filename: str | None = Field(default=None, max_length=255)
    attachment_content_base64: str | None = Field(default=None)


class OutreachSendResponse(BaseModel):
    """Result of a successful send."""

    status: str = "sent"
    # Gmail's id for the sent message (from users.messages.send), for tracing.
    message_id: str | None = None
    to_email: EmailStr
