"""Typed exceptions for the email-verification engine.

These let callers distinguish *infrastructure* failures (proxy down, DNS dead)
from *business* outcomes (address not found). Business outcomes are returned as
:class:`~app.services.email_verification.models.EmailVerificationResult`; only
unrecoverable infrastructure faults raise.
"""

from __future__ import annotations


class EmailVerificationError(Exception):
    """Base class for all engine errors."""


class DnsResolutionError(EmailVerificationError):
    """MX resolution failed for a transport reason (timeout, server failure).

    Distinct from "domain has no MX records", which is a normal business result.
    """


class ProxyConnectionError(EmailVerificationError):
    """The SOCKS5 proxy could not be reached or refused the tunnel."""
