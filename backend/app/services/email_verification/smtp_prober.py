"""SMTP recipient probing over a SOCKS5 proxy.

Integration strategy (verified against current upstream docs):

* ``python-socks`` (``python_socks.async_.asyncio.Proxy.from_url``) opens the
  SOCKS5 tunnel and ``proxy.connect(dest_host, dest_port)`` returns a *standard,
  non-blocking* Python socket already connected to the MX server.
* ``aiosmtplib.SMTP`` accepts that socket via its ``sock=`` parameter, so all
  SMTP traffic flows through the proxy. We then drive the low-level command
  coroutines directly — ``helo`` / ``mail`` / ``rcpt`` / ``quit`` — each of which
  returns an ``SMTPResponse(code, message)`` named tuple.

A probe never sends ``DATA``: we ask the server whether it would *accept* the
recipient (RCPT TO) and immediately ``QUIT``. No mail is ever delivered.
"""

from __future__ import annotations

import asyncio
import socket

import aiosmtplib
from aiosmtplib import SMTPResponse
from python_socks import ProxyError, ProxyTimeoutError
from python_socks.async_.asyncio import Proxy

from app.core.config import EmailVerificationSettings
from app.core.logging import get_logger
from app.services.email_verification.exceptions import ProxyConnectionError
from app.services.email_verification.models import SmtpProbeResult

logger = get_logger(__name__)

# RCPT TO reply codes that definitively mean "this mailbox does not exist".
# Everything else non-2xx is treated as inconclusive (transient/policy), which
# is the safe default — we never assert "not found" on a 4xx greylist.
_HARD_REJECT_CODES = frozenset({550, 551, 553})


class SmtpProber:
    """Probes recipient deliverability for a single MX host via SOCKS5.

    The prober is stateless beyond its settings, so one instance is safe to
    share across concurrent verification runs.
    """

    def __init__(self, settings: EmailVerificationSettings) -> None:
        self._settings = settings

    async def _open_proxied_socket(self, mx_host: str) -> socket.socket:
        """Open a SOCKS5 tunnel to ``mx_host:smtp_port`` and return the socket.

        Raises:
            ProxyConnectionError: If the proxy is unreachable, times out, or
                refuses to establish the tunnel.
        """
        if not self._settings.proxy_enabled:
            raise ProxyConnectionError("no SOCKS5 proxy configured (PROXY_URL is empty)")

        proxy = Proxy.from_url(self._settings.proxy_url)
        try:
            return await proxy.connect(
                dest_host=mx_host,
                dest_port=self._settings.smtp_port,
                timeout=self._settings.smtp_connect_timeout_seconds,
            )
        except ProxyTimeoutError as exc:
            raise ProxyConnectionError(f"proxy timed out reaching {mx_host}") from exc
        except ProxyError as exc:
            raise ProxyConnectionError(f"proxy refused tunnel to {mx_host}: {exc}") from exc
        except (OSError, asyncio.TimeoutError) as exc:
            raise ProxyConnectionError(f"cannot reach proxy: {exc}") from exc

    async def probe(self, email: str, mx_host: str) -> SmtpProbeResult:
        """Run a single HELO / MAIL FROM / RCPT TO / QUIT probe.

        This method does not raise for SMTP-level rejections — those are encoded
        in the returned :class:`SmtpProbeResult`. It only raises
        :class:`ProxyConnectionError` when the proxy itself is unusable (a fault
        that affects *every* probe and should abort the whole run).
        """
        sock = await self._open_proxied_socket(mx_host)

        # Hand the connected socket to aiosmtplib. With ``sock=`` set we must not
        # pass hostname/port; aiosmtplib reads the server banner on connect().
        client = aiosmtplib.SMTP(
            sock=sock,
            timeout=self._settings.smtp_command_timeout_seconds,
        )
        try:
            await client.connect()
            await client.helo(hostname=self._settings.helo_hostname)
            await client.mail(self._settings.mail_from)
            response: SMTPResponse = await client.rcpt(email)
            result = self._interpret(email, response)
        except aiosmtplib.SMTPResponseException as exc:
            # A command was rejected with a status code (e.g. RCPT 550). Encode
            # it rather than raising: it's a business signal, not a failure.
            result = self._interpret(
                email, SMTPResponse(exc.code, str(exc.message))
            )
        except (aiosmtplib.SMTPException, asyncio.TimeoutError, OSError) as exc:
            logger.warning(
                "smtp_probe_transport_error",
                extra={"email": email, "mx_host": mx_host, "error": str(exc)},
            )
            result = SmtpProbeResult(email=email, deliverable=False, error=str(exc))
        finally:
            await self._safe_quit(client)

        logger.info(
            "smtp_probe_result",
            extra={
                "email": email,
                "mx_host": mx_host,
                "deliverable": result.deliverable,
                "smtp_code": result.smtp_code,
            },
        )
        return result

    @staticmethod
    def _interpret(email: str, response: SMTPResponse) -> SmtpProbeResult:
        """Map an SMTP RCPT reply onto a :class:`SmtpProbeResult`."""
        code = response.code
        message = (response.message or "").strip().replace("\n", " ")[:512]
        return SmtpProbeResult(
            email=email,
            deliverable=200 <= code < 300,
            smtp_code=code,
            smtp_message=message,
        )

    @staticmethod
    def is_hard_reject(result: SmtpProbeResult) -> bool:
        """Whether the reply is a definitive "no such mailbox"."""
        return result.smtp_code in _HARD_REJECT_CODES

    @staticmethod
    async def _safe_quit(client: aiosmtplib.SMTP) -> None:
        """QUIT and close, swallowing errors — the socket is closing anyway."""
        try:
            await client.quit()
        except (aiosmtplib.SMTPException, asyncio.TimeoutError, OSError):
            try:
                client.close()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
