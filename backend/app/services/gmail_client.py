"""Gmail API integration — the cold-outreach *sending* seam.

This module is the only place that talks to Gmail. It uses the OAuth 2.0
installed-app ("Desktop App") flow: on the first send it opens a browser for
consent and writes ``token.json``; every subsequent send reuses that token,
refreshing it silently when it expires. This makes it a developer/single-user
tool by design — the consent step needs a local browser, so it is meant to run
on the operator's machine, not a headless server.

The google-api-python-client is synchronous, so every blocking call (auth,
service build, send) is pushed to a worker thread via :func:`asyncio.to_thread`
and the public API (:meth:`GmailClient.send_email`) is async — keeping the event
loop free, consistent with the rest of the service layer.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
from email.message import EmailMessage
from functools import lru_cache
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.discovery import Resource

from app.core.config import get_gmail_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Least-privilege scope: send-only. Gmail rejects a cached token whose scopes
# don't match, so changing this list invalidates an existing token.json (the user
# must re-consent) — keep it minimal and stable.
_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _guess_mimetype(filename: str | None) -> str:
    """Best-effort ``maintype/subtype`` for an attachment filename.

    Falls back to ``application/octet-stream`` for unknown/missing extensions —
    a safe generic binary type the recipient's client can still download.
    """
    if filename:
        guessed, _ = mimetypes.guess_type(filename)
        if guessed:
            return guessed
    return "application/octet-stream"


class GmailClient:
    """Sends email through the Gmail API using a cached OAuth user token.

    Instantiation is cheap (it only reads settings); the OAuth handshake and the
    API service are built lazily on the first send and then cached on the
    instance, so a single (DI-provided) client authenticates once per process.
    """

    def __init__(self) -> None:
        self._settings = get_gmail_settings()
        # Built lazily on first send so construction never triggers OAuth / I/O.
        self._service = None
        # Serialises sends: this client is a process-wide singleton, but each
        # send runs in a worker thread, and (a) the google-api-python-client
        # service (httplib2.Http) is not thread-safe, and (b) two first-time
        # sends could otherwise both trigger consent and race the token.json
        # write. Email volume is low, so serialising is harmless.
        self._send_lock = asyncio.Lock()

    def _authenticate(self) -> Credentials:
        """Return valid OAuth credentials, running consent/refresh as needed.

        Synchronous and potentially blocking (a missing token opens a browser),
        so it must only be called from a worker thread (see :meth:`send_email`).
        Order of preference:
          1. Load ``token.json`` if present.
          2. If it is expired but has a refresh token, refresh it silently;
             if that fails (token revoked/expired — common in Testing mode,
             where refresh tokens last ~7 days), fall through to re-consent.
          3. Otherwise run the installed-app consent flow on a local loopback
             server (``port=0`` picks a free port, matching Google's quickstart).
        Any newly obtained/refreshed token is written back to ``token.json``.
        """
        token_path = self._settings.token_path
        creds: Credentials | None = None
        if Path(token_path).exists():
            creds = Credentials.from_authorized_user_file(token_path, _SCOPES)

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            try:
                logger.info("gmail_token_refresh")
                creds.refresh(Request())
            except RefreshError:
                # Refresh token revoked/expired: drop it and re-run consent
                # rather than surfacing a hard error to the caller.
                logger.warning("gmail_token_refresh_failed_reconsent")
                creds = None

        if not creds or not creds.valid:
            logger.info("gmail_oauth_consent_flow")
            flow = InstalledAppFlow.from_client_secrets_file(
                self._settings.credentials_path, _SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Persist the (new or refreshed) token for the next process start. This
        # is best-effort: we already hold valid in-memory creds, so a failed
        # write must never abort the caller's send (see _persist_token).
        self._persist_token(creds)
        return creds

    def _persist_token(self, creds: Credentials) -> None:
        """Best-effort write of the (new/refreshed) token to disk.

        Prefer an atomic temp-write + rename so an interrupted write can never
        leave a half-written token.json. When the rename can't land on the
        target — e.g. token.json is a bind-mounted single file or sits on a
        Docker overlay filesystem, where ``os.replace()`` raises EBUSY ("Device
        or resource busy") — fall back to an in-place write (rewriting a
        bind-mounted file's contents is fine; only renaming *onto* it is not).
        If even that fails, log and carry on: the live creds are already valid,
        so persistence is an optimisation, not a precondition for sending.
        """
        token_path = self._settings.token_path
        token_json = creds.to_json()
        tmp_path = Path(f"{token_path}.tmp")
        try:
            tmp_path.write_text(token_json, encoding="utf-8")
            tmp_path.replace(token_path)
            return
        except OSError as exc:
            logger.warning(
                "gmail_token_atomic_write_failed", extra={"error": str(exc)}
            )
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

        try:
            Path(token_path).write_text(token_json, encoding="utf-8")
        except OSError:
            logger.exception("gmail_token_persist_failed")

    def _get_service(self) -> Resource:
        """Lazily build and cache the Gmail API service (authenticating first)."""
        if self._service is None:
            creds = self._authenticate()
            # cache_discovery=False: the on-disk discovery cache is noisy and
            # unnecessary for a single resource, and warns under modern Python.
            self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._service

    def _send_sync(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        attachment_filename: str | None,
        attachment_bytes: bytes | None,
    ) -> dict:
        """Blocking send — runs entirely inside a worker thread."""
        message = EmailMessage()
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body_text)

        # Attach the (already-decoded) file when present. Adding an attachment
        # promotes the message to multipart automatically.
        if attachment_bytes:
            maintype, _, subtype = (
                _guess_mimetype(attachment_filename).partition("/")
            )
            message.add_attachment(
                attachment_bytes,
                maintype=maintype,
                subtype=subtype,
                filename=attachment_filename or "attachment",
            )

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service = self._get_service()
        return (
            service.users()
            .messages()
            .send(userId="me", body={"raw": encoded_message})
            .execute()
        )

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        *,
        attachment_filename: str | None = None,
        attachment_bytes: bytes | None = None,
    ) -> dict:
        """Send a plain-text email (optionally with one attachment).

        Args:
            to_email: Recipient address.
            subject: Message subject.
            body_text: Plain-text body.
            attachment_filename: Filename for the attachment (e.g. ``"cv.pdf"``).
            attachment_bytes: Raw attachment bytes; attached only when present.

        Returns:
            Gmail's ``users.messages.send`` response dict (notably ``id`` — the
            sent message id — and ``threadId``).

        Raises:
            googleapiclient.errors.HttpError: On a Gmail API error (the caller
                translates it into an HTTP response). Auth/credential errors
                propagate as their own exception types.
        """
        async with self._send_lock:
            result = await asyncio.to_thread(
                self._send_sync,
                to_email,
                subject,
                body_text,
                attachment_filename,
                attachment_bytes,
            )
        logger.info(
            "gmail_email_sent",
            extra={
                "to": to_email,
                "message_id": result.get("id"),
                "has_attachment": bool(attachment_bytes),
            },
        )
        return result


@lru_cache
def get_gmail_client() -> GmailClient:
    """Return a process-wide cached :class:`GmailClient` (DI provider).

    Cached so the OAuth token is loaded/authorised once and the API service is
    reused across requests. FastAPI routes depend on this; tests override it via
    ``app.dependency_overrides``.
    """
    return GmailClient()
