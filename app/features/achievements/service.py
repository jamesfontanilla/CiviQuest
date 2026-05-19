"""Achievement service: criterion evaluator + read-side projection.

Wired in two places:

- :meth:`AchievementService.evaluate_after_xp_event` is called by
  :meth:`app.features.xp.service.XPService.award` immediately after the
  main XP event has been persisted. It walks every achievement
  definition the user has not yet been granted, evaluates the
  criterion against the just-recorded :class:`XPEvent` and / or the
  refreshed :class:`UserXP` cache row, and inserts a grant for each
  satisfied criterion. The list of newly-granted rows is returned so
  the caller can fan them out to the notification surface (Req 13.2 —
  one ``achievement_unlocked`` toast per grant).
- :meth:`AchievementService.list_for_user` is the read-side projection
  for ``GET /v1/achievements/me``. It joins each grant against its
  metadata so the response carries ``title``, ``description``, and
  ``granted_at`` without the client having to round-trip a second
  endpoint for the badge label.

Criterion semantics (matches :mod:`app.features.achievements.seed`):

- ``FIRST_LESSON`` — granted on the first ``LESSON_FIRST_COMPLETE``
  XP event for the user.
- ``FIRST_PERFECT_SUBTOPIC_QUIZ`` — granted on the first
  ``QUIZ_PERFECT`` XP event.
- ``FIRST_TOPIC_PASSED`` — granted on the first ``QUIZ_PASS`` event
  with ``amount == 100`` (Req 8.4 — topic-quiz pass amount).
- ``FIRST_MODULE_PASSED`` — granted on the first ``QUIZ_PASS`` event
  with ``amount == 250`` (Req 9.4 — module-quiz pass amount).
- ``FIRST_MOCK_PASSED`` — granted on the first ``MOCK_PASS`` event.
- ``STREAK_N_DAYS`` — granted when the user's ``streak_count`` reaches
  ``criterion_value["days"]`` on this event's rollover.
- ``LEVEL_N`` — granted when the user's ``level`` reaches
  ``criterion_value["level"]`` after this event.

Property 23 — Achievement uniqueness — is enforced at three layers:

1. The "already granted?" set check in this service short-circuits any
   re-evaluation of an achievement the user already holds.
2. :meth:`AchievementRepository.grant` does its own pre-insert lookup.
3. The UNIQUE constraint on ``user_achievements(user_id, achievement_id)``
   is the storage-level backstop for any race window between the
   service's check and the repository insert.

The service receives every repository it might consult through the
constructor. ``quiz_repo``, ``mock_repo``, and ``progress_repo`` aren't
read by the current criterion set — the discriminants we need are all
on the XP event or on ``user_xp`` — but they're plumbed in so future
criteria (e.g. "complete every lesson in a module") can land without
touching the constructor signature.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.features.achievements.models import Achievement, UserAchievement
from app.features.achievements.repository import AchievementRepository
from app.features.achievements.schemas import UserAchievementResponse
from app.features.achievements.seed import (
    CRITERION_DAILY_GOAL_N,
    CRITERION_FIRST_LESSON,
    CRITERION_FIRST_MOCK_PASSED,
    CRITERION_FIRST_MODULE_PASSED,
    CRITERION_FIRST_PERFECT_SUBTOPIC_QUIZ,
    CRITERION_FIRST_TOPIC_PASSED,
    CRITERION_LEVEL_N,
    CRITERION_STREAK_N_DAYS,
    CRITERION_TOURNAMENT_WINNER,
)
from app.features.mock_exams.repository import MockExamRepository
from app.features.progress.repository import ProgressRepository
from app.features.quizzes.repository import QuizRepository
from app.features.users.models import User
from app.features.xp.models import XPEvent, XPSource
from app.features.xp.repository import XPRepository


# Amount discriminants for the QUIZ_PASS branch. Topic and module
# quizzes both record their pass as ``QUIZ_PASS`` (the source enum
# doesn't distinguish them); the per-source amount is the only signal
# available at the XP event boundary. These constants must stay in sync
# with the per-scope amounts in
# :mod:`app.features.quizzes.service` (Req 8.4 — topic 100; Req 9.4 —
# module 250).
_TOPIC_QUIZ_PASS_AMOUNT = 100
_MODULE_QUIZ_PASS_AMOUNT = 250


def _utcnow() -> datetime:
    """Aware UTC ``now`` so callers can pin time during tests."""
    return datetime.now(tz=timezone.utc)


class AchievementService:
    """Evaluate, grant, and surface achievements (Req 13.1, 13.2, 13.3)."""

    def __init__(
        self,
        *,
        ach_repo: AchievementRepository,
        xp_repo: XPRepository,
        quiz_repo: QuizRepository,
        mock_repo: MockExamRepository,
        progress_repo: ProgressRepository,
    ) -> None:
        self._ach_repo = ach_repo
        self._xp_repo = xp_repo
        # Plumbed for forward compatibility — see module docstring.
        self._quiz_repo = quiz_repo
        self._mock_repo = mock_repo
        self._progress_repo = progress_repo

    # ------------------------------------------------------------------
    # read-side
    # ------------------------------------------------------------------

    def list_for_user(self, user_id: int) -> list[UserAchievementResponse]:
        """Return ``user_id``'s grants joined with achievement metadata.

        Used by ``GET /v1/achievements/me``. Each grant carries the
        achievement's ``title`` and ``description`` so the client can
        render the badge without a second round-trip.
        """
        grants = self._ach_repo.list_for_user(user_id)
        if not grants:
            return []

        # Pre-fetch the metadata in one query so we don't N+1.
        achievements = {a.id: a for a in self._ach_repo.list_all()}

        out: list[UserAchievementResponse] = []
        for grant in grants:
            ach = achievements.get(grant.achievement_id)
            if ach is None:
                # Defensive: a grant referencing a missing achievement
                # would be a data-integrity bug. Skip it on the wire
                # rather than 500-ing the entire profile.
                continue  # pragma: no cover
            out.append(
                UserAchievementResponse(
                    achievement_id=grant.achievement_id,
                    title=ach.title,
                    description=ach.description,
                    rarity=ach.rarity,
                    icon=ach.icon,
                    xp_reward=ach.xp_reward,
                    granted_at=grant.granted_at,
                )
            )
        return out

    # ------------------------------------------------------------------
    # evaluator
    # ------------------------------------------------------------------

    def evaluate_after_xp_event(
        self,
        *,
        user: User,
        xp_event: XPEvent,
        now: datetime | None = None,
    ) -> list[UserAchievement]:
        """Evaluate every criterion and grant any newly-satisfied achievement.

        Called by :meth:`XPService.award` after the main event row has
        been persisted. Returns the list of newly-granted
        :class:`UserAchievement` rows so the caller can fan them out to
        the notification surface (one ``achievement_unlocked`` toast
        per grant — Req 13.2).

        Logic:

        1. Load every achievement definition.
        2. Refresh the ``user_xp`` cache row so streak/level checks see
           the just-applied update.
        3. Build the "already granted" set so we never re-evaluate a
           held achievement (Property 23 — at most one grant per pair).
        4. For each not-already-granted achievement, switch on
           ``criterion_kind`` and check the rule against the event +
           cache row.
        5. Grant via the repository; collect every row that gets newly
           inserted.
        """
        when = now or _utcnow()
        defs = self._ach_repo.list_all()
        if not defs:
            return []

        already = self._ach_repo.list_user_achievement_ids(user.id)
        # Refresh the cache row so streak/level checks read the
        # post-award snapshot.
        user_xp = self._xp_repo.get_or_create_user_xp(user.id)

        newly_granted: list[UserAchievement] = []
        for ach in defs:
            if ach.id in already:
                continue
            if not self._criterion_satisfied(
                ach=ach, xp_event=xp_event, user_xp_streak=user_xp.streak_count,
                user_xp_level=user_xp.level,
            ):
                continue
            grant = self._ach_repo.grant(
                user_id=user.id,
                achievement_id=ach.id,
                granted_at=when,
                source_xp_event_id=xp_event.id,
            )
            # Defensive: ``grant`` is idempotent. If a parallel pass
            # already inserted between our ``already`` snapshot and the
            # call above, the returned row was *not* newly created;
            # detect that by checking whether the row's id is present
            # in our local "newly granted" set is overkill. We simply
            # re-check the post-write granted set below and only count
            # rows whose ``granted_at`` matches ``when`` — but that's
            # fragile across clock skew. Cleaner: compare with the
            # pre-evaluation ``already`` set.
            if grant.achievement_id not in already:
                newly_granted.append(grant)
                already.add(grant.achievement_id)

        return newly_granted

    # ------------------------------------------------------------------
    # criterion dispatch
    # ------------------------------------------------------------------

    def _criterion_satisfied(
        self,
        *,
        ach: Achievement,
        xp_event: XPEvent,
        user_xp_streak: int,
        user_xp_level: int,
    ) -> bool:
        """Return True iff ``ach``'s criterion is satisfied by this event.

        The switch is exhaustive over the criterion-kind constants
        defined in :mod:`app.features.achievements.seed`. An unknown
        kind returns ``False`` so a rogue admin-imported row can't
        trigger spurious grants.
        """
        kind = ach.criterion_kind
        source = xp_event.source

        if kind == CRITERION_FIRST_LESSON:
            return source == XPSource.LESSON_FIRST_COMPLETE.value

        if kind == CRITERION_FIRST_PERFECT_SUBTOPIC_QUIZ:
            return source == XPSource.QUIZ_PERFECT.value

        if kind == CRITERION_FIRST_TOPIC_PASSED:
            return (
                source == XPSource.QUIZ_PASS.value
                and xp_event.amount == _TOPIC_QUIZ_PASS_AMOUNT
            )

        if kind == CRITERION_FIRST_MODULE_PASSED:
            return (
                source == XPSource.QUIZ_PASS.value
                and xp_event.amount == _MODULE_QUIZ_PASS_AMOUNT
            )

        if kind == CRITERION_FIRST_MOCK_PASSED:
            return source == XPSource.MOCK_PASS.value

        if kind == CRITERION_STREAK_N_DAYS:
            target = int(ach.criterion_value.get("days", 0))
            return target > 0 and user_xp_streak >= target

        if kind == CRITERION_LEVEL_N:
            target = int(ach.criterion_value.get("level", 0))
            return target > 0 and user_xp_level >= target

        if kind == CRITERION_DAILY_GOAL_N:
            # Evaluated externally by the gamification service; not triggered
            # by a single XP event. Return False here — the gamification
            # service grants these directly.
            return False

        if kind == CRITERION_TOURNAMENT_WINNER:
            # Granted directly by the tournament service when a tournament
            # completes and a winner is determined. Not triggered by XP events.
            return False

        return False
