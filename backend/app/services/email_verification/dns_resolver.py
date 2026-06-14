"""Asynchronous MX resolution via ``dnspython``'s ``dns.asyncresolver``.

We return MX exchange hostnames ordered by ascending preference (RFC 5321: the
lowest preference value is tried first). "No MX records" is a *normal* result
returned as an empty list; only transport faults raise ``DnsResolutionError``.
"""

from __future__ import annotations

import dns.asyncresolver
import dns.exception
import dns.resolver

from app.core.logging import get_logger
from app.services.email_verification.exceptions import DnsResolutionError

logger = get_logger(__name__)


async def resolve_mx_hosts(
    domain: str,
    *,
    timeout: float,
    lifetime: float,
) -> list[str]:
    """Resolve MX hosts for ``domain``, ordered by ascending preference.

    Args:
        domain: The domain to look up (already normalised).
        timeout: Per-attempt timeout in seconds.
        lifetime: Total resolution budget in seconds.

    Returns:
        Exchange hostnames (trailing dot stripped), best first. Empty list when
        the domain genuinely has no MX records.

    Raises:
        DnsResolutionError: On timeout or a server-side failure (SERVFAIL).
    """
    resolver = dns.asyncresolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = lifetime

    try:
        answer = await resolver.resolve(domain, "MX")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        # Domain exists but publishes no MX (or doesn't exist): not deliverable
        # here, but not an error condition for us.
        logger.info("mx_no_records", extra={"domain": domain})
        return []
    except dns.resolver.NoNameservers as exc:
        raise DnsResolutionError(f"no nameservers could answer for {domain}") from exc
    except dns.exception.Timeout as exc:
        raise DnsResolutionError(f"DNS timeout resolving MX for {domain}") from exc
    except dns.exception.DNSException as exc:  # pragma: no cover - defensive
        raise DnsResolutionError(f"DNS failure resolving MX for {domain}: {exc}") from exc

    records = sorted(answer, key=lambda r: r.preference)
    hosts = [str(record.exchange).rstrip(".") for record in records]
    logger.info("mx_resolved", extra={"domain": domain, "mx_hosts": hosts})
    return hosts
