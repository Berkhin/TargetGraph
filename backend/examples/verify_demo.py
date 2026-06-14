"""Manual smoke test for the email-verification engine.

Usage (from the ``backend`` directory, with PROXY_URL exported):

    python -m examples.verify_demo "Alex" "Mercer" "company.com"

This performs *real* DNS + SMTP traffic through the configured SOCKS5 proxy, so
run it only against domains you are authorised to probe.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from app.core.logging import configure_logging
from app.services.email_verification import (
    EmailVerificationRequest,
    EmailVerificationService,
)


async def _main() -> None:
    configure_logging(logging.INFO)
    if len(sys.argv) != 4:
        print(__doc__)
        raise SystemExit(2)

    first, last, domain = sys.argv[1], sys.argv[2], sys.argv[3]
    service = EmailVerificationService()
    result = await service.verify(
        EmailVerificationRequest(first_name=first, last_name=last, domain=domain)
    )
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
