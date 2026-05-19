"""SMTP-based OTP delivery adapter.

For MVP this is an env-gated stub. When ``SMTP_HOST`` is unset (or any
constructor arg is passed as ``None``) the adapter is a no-op that returns
``False`` from :meth:`send_otp` without raising. When a host is configured
the adapter logs a structured "would send" line (without the OTP code, per
Req 21.3 redaction policy) and returns ``True`` so callers can exercise the
success path during integration runs.

Live ``smtplib.SMTP`` integration lands in a future task; until then this
adapter exists only so the service layer can depend on a stable surface.
"""

from __future__ import annotations

import logging
import os

from app.infrastructure.external.base import ExternalServiceBase

logger = logging.getLogger(__name__)


class SmtpOtpSender(ExternalServiceBase):
    """Adapter that would send an OTP code via SMTP.

    Constructor arguments default to environment variables when ``None`` is
    passed, matching the constructor-injection convention from
    ``ExternalServiceBase``. Tests can override every value without touching
    ``os.environ``.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        from_addr: str | None = None,
    ) -> None:
        self.host = host if host is not None else os.environ.get("SMTP_HOST")
        env_port = os.environ.get("SMTP_PORT")
        self.port = port if env_port is None else int(env_port)
        self.username = username if username is not None else os.environ.get("SMTP_USER")
        self.password = password if password is not None else os.environ.get("SMTP_PASSWORD")
        self.from_addr = (
            from_addr if from_addr is not None else os.environ.get("SMTP_FROM_ADDR")
        )

    def send_otp(self, to_email: str, code: str, purpose: str) -> bool:
        """Deliver the OTP code via SMTP (Resend or any SMTP provider).

        Returns ``False`` (no-op) when no SMTP host is configured.
        Returns ``True`` on successful send. Logs errors but does not raise
        so the caller can fall back to offline delivery.
        """
        if not self.host:
            return False

        import smtplib
        from email.mime.text import MIMEText

        purpose_label = "email verification" if purpose == "VERIFY_EMAIL" else "password reset"
        subject = f"CiviQuest - Your {purpose_label} code"
        body = (
            f"Your CiviQuest verification code is:\n\n"
            f"    {code}\n\n"
            f"This code expires in 5 minutes.\n\n"
            f"If you didn't request this, you can safely ignore this email."
        )

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self.from_addr or f"noreply@{self.host}"
        msg["To"] = to_email

        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as server:
                server.starttls()
                if self.username and self.password:
                    server.login(self.username, self.password)
                server.sendmail(msg["From"], [to_email], msg.as_string())
            logger.info(
                "smtp_otp_sender.sent",
                extra={"to_email": to_email, "purpose": purpose},
            )
            return True
        except Exception as exc:
            logger.error(
                "smtp_otp_sender.failed: %s",
                str(exc),
                extra={"to_email": to_email, "purpose": purpose},
            )
            return False

    def health_check(self) -> bool:
        """Return True iff a host is configured.

        A real TCP probe is intentionally avoided so health checks don't
        introduce a network dependency in tests.
        """
        return bool(self.host)
