"""Resend-backed OTP email delivery adapter.

Sends transactional email via the Resend API (https://resend.com) using
only Python's stdlib ``urllib`` — no extra dependency required.

Free tier: 3,000 emails/month, 100/day. Sufficient for ~1,000 active users
doing OTP and password-reset flows.

Configuration (environment variables):
    RESEND_API_KEY   — required for live sending (get from resend.com dashboard)
    EMAIL_FROM_ADDR  — sender address, must be a verified Resend domain
                       (default: "noreply@<your-verified-domain>")

When ``RESEND_API_KEY`` is unset the adapter is a no-op that logs a warning
and returns ``False``, so local dev and tests work without credentials.

Security note (security-policy.md): the OTP code is sent in the email body
but is NOT logged anywhere in this module. The structured log line emitted
on success/failure contains only the recipient address and purpose.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Final

from app.infrastructure.external.base import ExternalServiceBase

logger = logging.getLogger(__name__)

_RESEND_API_URL: Final[str] = "https://api.resend.com/emails"


class SmtpOtpSender(ExternalServiceBase):
    """Adapter that delivers OTP codes via the Resend email API.

    The class is named ``SmtpOtpSender`` to preserve the existing injection
    surface — all call sites use this name and no rename is needed.

    Constructor arguments default to environment variables when ``None`` is
    passed, matching the constructor-injection convention from
    ``ExternalServiceBase``. Tests can override every value without touching
    ``os.environ``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        from_addr: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("RESEND_API_KEY", "")
        self.from_addr = (
            from_addr
            if from_addr is not None
            else os.environ.get("EMAIL_FROM_ADDR", "CiviQuest <noreply@civiquest.app>")
        )

    # ------------------------------------------------------------------
    # public surface
    # ------------------------------------------------------------------

    def send_otp(self, to_email: str, code: str, purpose: str) -> bool:
        """Send the OTP ``code`` to ``to_email`` via Resend.

        Returns ``True`` on success, ``False`` on any failure (missing key,
        network error, API error). Logs errors but does not raise so the
        caller can fall back to offline delivery.

        The ``code`` value is intentionally NOT included in any log line
        (Req 21.3 redaction policy).
        """
        if not self.api_key:
            logger.warning(
                "resend_otp_sender.skipped: RESEND_API_KEY not set",
                extra={"to_email": to_email, "purpose": purpose},
            )
            return False

        subject, body = self._build_message(code, purpose)
        payload = json.dumps(
            {
                "from": self.from_addr,
                "to": [to_email],
                "subject": subject,
                "text": body,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            _RESEND_API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
            if status in (200, 201):
                logger.info(
                    "resend_otp_sender.sent",
                    extra={"to_email": to_email, "purpose": purpose},
                )
                return True
            logger.error(
                "resend_otp_sender.unexpected_status: %s",
                status,
                extra={"to_email": to_email, "purpose": purpose},
            )
            return False
        except urllib.error.HTTPError as exc:
            logger.error(
                "resend_otp_sender.http_error: %s %s",
                exc.code,
                exc.reason,
                extra={"to_email": to_email, "purpose": purpose},
            )
            return False
        except Exception as exc:
            logger.error(
                "resend_otp_sender.failed: %s",
                str(exc),
                extra={"to_email": to_email, "purpose": purpose},
            )
            return False

    def health_check(self) -> bool:
        """Return True iff a Resend API key is configured."""
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_message(code: str, purpose: str) -> tuple[str, str]:
        """Return ``(subject, plain-text body)`` for the given purpose."""
        if purpose == "VERIFY_EMAIL":
            purpose_label = "email verification"
        else:
            purpose_label = "password reset"

        subject = f"CiviQuest — Your {purpose_label} code"
        body = (
            f"Your CiviQuest {purpose_label} code is:\n\n"
            f"    {code}\n\n"
            f"This code expires in 5 minutes. Do not share it with anyone.\n\n"
            f"If you didn't request this, you can safely ignore this email."
        )
        return subject, body
