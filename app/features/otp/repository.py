"""Repository for OTP persistence and rate-limit queries.

All write helpers commit eagerly so the service layer can sequence
``invalidate_unused_for`` -> ``create`` -> ``deliver`` with each step
visible to subsequent queries (e.g. the rate-limit count must observe the
just-issued row).

Time is passed in via the ``now`` keyword argument with a UTC default so
property tests can pin the clock; production callers pass nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import Session

from app.features.otp.models import OTP, OTPPurpose
from app.infrastructure.repositories.base import BaseRepository


def _utcnow() -> datetime:
    """Aware UTC `now`. ``datetime.utcnow`` is naive and deprecated in 3.12+."""
    return datetime.now(tz=timezone.utc)


class OTPRepository(BaseRepository[OTP]):
    """Persistence for ``OTP`` rows."""

    model = OTP

    def __init__(self, db: Session) -> None:
        super().__init__(db=db)

    def count_issuances_in_last_60min(
        self, user_id: int, *, now: datetime | None = None
    ) -> int:
        """Count OTPs issued for ``user_id`` in the last 60 minutes (Req 2.6).

        Counts rows regardless of purpose so that PASSWORD_RESET and
        VERIFY_EMAIL share the rate budget. The service layer can refine this
        per-purpose later if the spec changes; for now Req 2.6 reads as a
        per-account cap.
        """
        cutoff = (now or _utcnow()) - timedelta(minutes=60)
        stmt = (
            select(func.count())
            .select_from(OTP)
            .where(OTP.user_id == user_id, OTP.created_at >= cutoff)
        )
        return int(self.db.execute(stmt).scalar_one())

    def invalidate_unused_for(self, user_id: int, purpose: OTPPurpose) -> int:
        """Mark every unused/non-invalidated OTP for ``(user_id, purpose)`` as
        invalidated. Returns the number of rows updated (Req 2.5)."""
        stmt = (
            update(OTP)
            .where(
                OTP.user_id == user_id,
                OTP.purpose == purpose.value,
                OTP.used.is_(False),
                OTP.invalidated.is_(False),
            )
            .values(invalidated=True)
        )
        result = self.db.execute(stmt)
        self.db.commit()
        return int(result.rowcount or 0)

    def get_latest_active(
        self, user_id: int, purpose: OTPPurpose, *, now: datetime | None = None
    ) -> OTP | None:
        """Return the newest unused/non-invalidated/unexpired OTP, if any.

        Used by the verify path before bcrypt-comparing the supplied code
        (Req 2.2). Order is ``created_at DESC`` so the latest issuance wins.
        """
        cutoff = now or _utcnow()
        stmt = (
            select(OTP)
            .where(
                OTP.user_id == user_id,
                OTP.purpose == purpose.value,
                OTP.used.is_(False),
                OTP.invalidated.is_(False),
                OTP.expires_at > cutoff,
            )
            .order_by(desc(OTP.created_at))
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def bump_attempt(self, otp: OTP) -> OTP:
        """Increment ``attempt_count`` and persist (Req 2.7)."""
        otp.attempt_count += 1
        self.db.commit()
        self.db.refresh(otp)
        return otp

    def mark_used(self, otp: OTP) -> OTP:
        """Mark an OTP as consumed (Req 2.2)."""
        otp.used = True
        self.db.commit()
        self.db.refresh(otp)
        return otp

    def mark_invalidated(self, otp: OTP) -> OTP:
        """Mark an OTP as invalidated (Req 2.5, 2.7)."""
        otp.invalidated = True
        self.db.commit()
        self.db.refresh(otp)
        return otp
