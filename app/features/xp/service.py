"""XP business logic (Task 9.3).

Two responsibilities live here:

* :meth:`XPService.award` — append an :class:`~app.features.xp.models.XPEvent`
  for a qualifying source, refresh the
  :class:`~app.features.xp.models.UserXP` cache, and trigger the streak
  rollover for activity-style sources. Validates the closed-source enum
  (Req 11.1) and the non-negative-amount invariant (Req 11.7) before
  hitting the DB so user-facing errors come back as 4xx instead of 500.
* :meth:`XPService.get_user_xp_view` — read-side projection that applies
  the 36-hour streak decay (Req 11.6) at request time, returning a clean
  :class:`~app.features.xp.schemas.UserXPResponse`.

The service receives the repositories via constructor injection per
``code-conventions.md``. Notification fan-out (Req 11.5 ``level_up``
toast, Req 13.1 achievement evaluator) is deliberately deferred to later
tasks; the surfaces are commented as ``TODO`` markers so the integration
points are obvious when the slices land.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status

from app.features.users.models import User
from app.features.users.repository import UserRepository
from app.features.xp.algorithms.streak import (
    on_qualifying_activity,
    streak_for_read,
)
from app.features.xp.models import UserXP, XPEvent, XPSource
from app.features.xp.repository import XPRepository
from app.features.xp.schemas import UserXPResponse

if TYPE_CHECKING:
    from app.features.achievements.service import AchievementService


# Per-source default amounts (Req 7.6, 7.7, 8.4, 9.4, 10.6, 11.2, 11.3).
#
# ``QUIZ_PASS`` carries the **subtopic** non-perfect passing amount
# (Req 7.7). Topic / module / mock callers should pass an explicit
# ``amount`` argument to :meth:`XPService.award` rather than relying on the
# default — the topic-quiz pass is 100 XP (Req 8.4) and the module-quiz
# pass is 250 XP (Req 9.4); both override this default. ``MOCK_PASS`` here
# is the spec value of 500 XP (Req 10.6).
DEFAULT_AMOUNT_BY_SOURCE: dict[XPSource, int] = {
    XPSource.LESSON_FIRST_COMPLETE: 20,  # Req 11.2
    XPSource.QUIZ_PERFECT: 50,  # Req 7.6
    XPSource.QUIZ_PASS: 20,  # Req 7.7 (subtopic default)
    XPSource.MOCK_PASS: 500,  # Req 10.6
    XPSource.STREAK_DAY: 25,  # Req 11.3
}

# Sources that count as "qualifying activity" for the streak rollover
# (Req 11.3). ``ADMIN_CORRECTION`` and ``STREAK_DAY`` are excluded:
# admin corrections are not user-driven, and ``STREAK_DAY`` events are
# *produced by* the rollover (recursion guard — emitting one would not
# re-trigger another).
_QUALIFYING_ACTIVITY_SOURCES: frozenset[XPSource] = frozenset(
    {
        XPSource.LESSON_FIRST_COMPLETE,
        XPSource.QUIZ_PASS,
        XPSource.QUIZ_PERFECT,
        XPSource.MOCK_PASS,
    }
)


def _utcnow() -> datetime:
    """Aware UTC ``now`` so callers can pin time during tests."""
    return datetime.now(tz=timezone.utc)


class XPService:
    """Award XP, recompute level / streak, expose read-side view."""

    def __init__(
        self,
        *,
        xp_repo: XPRepository,
        user_repo: UserRepository,
        achievement_service: "AchievementService | None" = None,
    ) -> None:
        self._xp_repo = xp_repo
        # ``user_repo`` is wired in for parity with other slice services and
        # so future XP-related operations (e.g. admin corrections by email)
        # have it available without re-plumbing.
        self._user_repo = user_repo
        # Optional achievement evaluator (Task 15.2). When provided, the
        # service triggers it after every XP event so newly satisfied
        # achievements get granted immediately. Tests and historical
        # callers can leave it unset; the wire-up in
        # :func:`app.features.xp.router.get_xp_service` always supplies
        # one so production behaviour matches Req 13.1.
        self._achievement_service = achievement_service

    # ------------------------------------------------------------------
    # award
    # ------------------------------------------------------------------

    def award(
        self,
        *,
        user: User,
        source: XPSource,
        amount: int | None = None,
        occurred_at: datetime | None = None,
        source_ref_id: int | None = None,
        client_event_id: str | None = None,
    ) -> tuple[XPEvent, UserXP]:
        """Append an XP event for ``user`` (Req 11.1, 11.7).

        Order of operations:

        1. **Validate source.** ``source`` must be an :class:`XPSource`
           enum member. The closed-source CHECK on the DB is the
           backstop, but we raise a 400 here so the client sees a
           structured error instead of a 500 from an IntegrityError.
        2. **Idempotency by ``client_event_id``.** When a prior event
           with the same id exists for this user, return it as-is
           without inserting (Req 20.3 offline replay).
        3. **Resolve amount.** If ``amount`` is omitted, fall back to
           :data:`DEFAULT_AMOUNT_BY_SOURCE`. Topic / module quiz callers
           should always pass explicit amounts (100 / 250 / etc.).
        4. **Validate amount sign.** Negative amounts are only allowed
           when ``source == ADMIN_CORRECTION`` (Req 11.7).
        5. **Streak rollover.** For qualifying activity sources, compute
           the new streak count and award a ``STREAK_DAY`` event when
           the rollover transitions to a new day. The streak event is
           inserted *first* so the cumulative_xp moves chronologically
           through the rollover and then through the main event.
        6. **Insert main event.** Atomic with the cache refresh via
           :meth:`XPRepository.insert_event_and_recompute`.

        Returns:
            ``(event, user_xp)``. On idempotent replay, ``event`` is the
            previously persisted row and ``user_xp`` is the current
            cache state.

        Raises:
            HTTPException: 400 on validation failures (unknown source,
            illegal negative amount, missing default amount for
            ``ADMIN_CORRECTION``).
        """
        when = occurred_at or _utcnow()

        # 1. Source-enum validation.
        if not isinstance(source, XPSource):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_xp_source",
            )

        # 2. Idempotency replay.
        if client_event_id is not None:
            existing = self._xp_repo.get_event_by_client_event_id(
                client_event_id
            )
            if existing is not None and existing.user_id == user.id:
                user_xp = self._xp_repo.get_or_create_user_xp(user.id)
                return existing, user_xp

        # 3. Resolve amount.
        if amount is None:
            if source == XPSource.ADMIN_CORRECTION:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="admin_correction_requires_amount",
                )
            default = DEFAULT_AMOUNT_BY_SOURCE.get(source)
            if default is None:  # pragma: no cover - defensive guard
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="invalid_xp_source",
                )
            amount = default

        # 4. Sign validation.
        if amount < 0 and source != XPSource.ADMIN_CORRECTION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="negative_amount_not_allowed",
            )

        # 5. Streak rollover for qualifying activities.
        if source in _QUALIFYING_ACTIVITY_SOURCES:
            self._apply_streak_rollover(user=user, now_utc=when)

        # 6. Insert the main event + refresh cache atomically.
        event, user_xp = self._xp_repo.insert_event_and_recompute(
            user_id=user.id,
            source=source,
            amount=amount,
            occurred_at=when,
            source_ref_id=source_ref_id,
            client_event_id=client_event_id,
        )

        # TODO(Req 11.5): emit ``level_up`` toast via Notification_Service
        # when ``user_xp.level`` moved up vs. the prior value. The signal
        # is available here (insert_event_and_recompute stamps
        # ``level_reached_at == when`` exactly when the level rose).

        # Trigger the achievement evaluator (Task 15.2, Req 13.1). The
        # evaluator returns the list of newly granted achievements; the
        # caller (notification fan-out, Req 13.2) consumes them off the
        # service's return signature once that surface is wired up. For
        # now the result is dropped because no consumer exists yet.
        if self._achievement_service is not None:
            self._achievement_service.evaluate_after_xp_event(
                user=user, xp_event=event, now=when
            )
        return event, user_xp

    def _apply_streak_rollover(
        self, *, user: User, now_utc: datetime
    ) -> None:
        """Run :func:`on_qualifying_activity` and persist the result.

        When the rollover awards the day, also append a ``STREAK_DAY``
        XP event. The streak event is inserted **before** the caller's
        main event (the order in :meth:`award`) so the ledger reads
        chronologically: streak first, activity second.
        """
        user_xp = self._xp_repo.get_or_create_user_xp(user.id)
        new_streak, award_day = on_qualifying_activity(
            user=user, user_xp=user_xp, now_utc=now_utc
        )

        # Always stamp the activity time; this is what drives both the
        # next rollover decision and the read-side decay.
        z = ZoneInfo(user.tz_name)
        user_xp.streak_count = new_streak
        user_xp.last_activity_at = now_utc
        user_xp.last_streak_day = now_utc.astimezone(z).date()
        self._xp_repo.commit_streak_update(user_xp)

        if award_day:
            # Recurse into the ledger via the repository (not back into
            # ``award`` — that would re-enter the rollover branch and
            # loop). The CHECK constraint blesses the source.
            self._xp_repo.insert_event_and_recompute(
                user_id=user.id,
                source=XPSource.STREAK_DAY,
                amount=DEFAULT_AMOUNT_BY_SOURCE[XPSource.STREAK_DAY],
                occurred_at=now_utc,
            )

    # ------------------------------------------------------------------
    # get_user_xp_view
    # ------------------------------------------------------------------

    def get_user_xp_view(
        self, user: User, *, now: datetime | None = None
    ) -> UserXPResponse:
        """Return the decay-applied XP / level / streak view (Req 11.4, 11.6)."""
        when = now or _utcnow()
        user_xp = self._xp_repo.get_or_create_user_xp(user.id)
        return UserXPResponse(
            cumulative_xp=user_xp.cumulative_xp,
            level=user_xp.level,
            streak=streak_for_read(
                user=user, user_xp=user_xp, now_utc=when
            ),
        )
