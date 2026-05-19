"""Seed data for the achievements slice (Task 15.1, 15.5).

Two named lists:

- :data:`MVP_ACHIEVEMENTS` — the three achievements required to ship MVP
  (Task 15.1): ``FIRST_LESSON``, ``STREAK_7_DAYS``, ``LEVEL_10``.
- :data:`PHASE2_ACHIEVEMENTS` — the additional six achievements from
  Req 13.4 (Task 15.5): ``FIRST_PERFECT_SUBTOPIC_QUIZ``,
  ``FIRST_TOPIC_PASSED``, ``FIRST_MODULE_PASSED``,
  ``FIRST_MOCK_PASSED``, ``STREAK_30_DAYS``, ``LEVEL_25``.

The lists are deliberately separate (rather than a single
``ALL_ACHIEVEMENTS``) so the MVP seed loader can stay lean without
shipping evaluator paths that aren't yet wired through the rest of the
backend. :func:`seed_all_achievements` writes both for environments
that want the full Phase 2 set.

Each :class:`Achievement` row describes a criterion the evaluator
switches on:

- ``FIRST_LESSON`` — granted on the first ``LESSON_FIRST_COMPLETE``
  XP event (Req 13.4).
- ``FIRST_PERFECT_SUBTOPIC_QUIZ`` — granted on the first
  ``QUIZ_PERFECT`` XP event.
- ``FIRST_TOPIC_PASSED`` — granted on the first ``QUIZ_PASS`` event
  with amount=100 (the topic-quiz pass amount, Req 8.4).
- ``FIRST_MODULE_PASSED`` — granted on the first ``QUIZ_PASS`` event
  with amount=250 (the module-quiz pass amount, Req 9.4).
- ``FIRST_MOCK_PASSED`` — granted on the first ``MOCK_PASS`` event.
- ``STREAK_N_DAYS`` — granted when ``user_xp.streak_count >= N``;
  ``criterion_value`` carries ``{"days": N}``.
- ``LEVEL_N`` — granted when ``user_xp.level >= N``; ``criterion_value``
  carries ``{"level": N}``.

The amount-based discriminant for topic vs module passes is the only
practical signal available at the XP event boundary: both fire as
``QUIZ_PASS`` and the source row carries the amount but not the scope
level. The XP service caller (the quiz service) supplies the canonical
amounts in the spec, so the discriminant is reliable as long as those
amounts don't change. If they do, this seed needs to move with them
and the evaluator switch should reference shared constants.
"""

from __future__ import annotations

from app.features.achievements.models import Achievement
from app.features.achievements.repository import AchievementRepository


# Criterion-kind string constants. Kept here (next to the seed) so the
# evaluator and the seed agree on spelling and a typo on either side
# fails loudly at test time. The set is intentionally small — the
# evaluator's switch handles each one explicitly.
CRITERION_FIRST_LESSON = "FIRST_LESSON"
CRITERION_FIRST_PERFECT_SUBTOPIC_QUIZ = "FIRST_PERFECT_SUBTOPIC_QUIZ"
CRITERION_FIRST_TOPIC_PASSED = "FIRST_TOPIC_PASSED"
CRITERION_FIRST_MODULE_PASSED = "FIRST_MODULE_PASSED"
CRITERION_FIRST_MOCK_PASSED = "FIRST_MOCK_PASSED"
CRITERION_STREAK_N_DAYS = "STREAK_N_DAYS"
CRITERION_LEVEL_N = "LEVEL_N"


MVP_ACHIEVEMENTS: list[Achievement] = [
    Achievement(
        id="FIRST_LESSON",
        title="First Lesson",
        description="Complete your first lesson.",
        criterion_kind=CRITERION_FIRST_LESSON,
        criterion_value={},
        rarity="COMMON",
        icon="📖",
        xp_reward=10,
    ),
    Achievement(
        id="STREAK_7_DAYS",
        title="7-Day Streak",
        description="Maintain a 7-day learning streak.",
        criterion_kind=CRITERION_STREAK_N_DAYS,
        criterion_value={"days": 7},
        rarity="RARE",
        icon="🔥",
        xp_reward=50,
    ),
    Achievement(
        id="LEVEL_10",
        title="Level 10",
        description="Reach level 10.",
        criterion_kind=CRITERION_LEVEL_N,
        criterion_value={"level": 10},
        rarity="RARE",
        icon="⭐",
        xp_reward=100,
    ),
]


PHASE2_ACHIEVEMENTS: list[Achievement] = [
    Achievement(
        id="FIRST_PERFECT_SUBTOPIC_QUIZ",
        title="Perfect Score",
        description="Score 100% on a subtopic quiz.",
        criterion_kind=CRITERION_FIRST_PERFECT_SUBTOPIC_QUIZ,
        criterion_value={},
        rarity="COMMON",
        icon="💯",
        xp_reward=20,
    ),
    Achievement(
        id="FIRST_TOPIC_PASSED",
        title="Topic Champion",
        description="Pass your first topic quiz.",
        criterion_kind=CRITERION_FIRST_TOPIC_PASSED,
        criterion_value={},
        rarity="COMMON",
        icon="🏆",
        xp_reward=30,
    ),
    Achievement(
        id="FIRST_MODULE_PASSED",
        title="Module Master",
        description="Pass your first module quiz.",
        criterion_kind=CRITERION_FIRST_MODULE_PASSED,
        criterion_value={},
        rarity="RARE",
        icon="🎓",
        xp_reward=50,
    ),
    Achievement(
        id="FIRST_MOCK_PASSED",
        title="Mock Survivor",
        description="Pass your first mock exam.",
        criterion_kind=CRITERION_FIRST_MOCK_PASSED,
        criterion_value={},
        rarity="EPIC",
        icon="🛡️",
        xp_reward=100,
    ),
    Achievement(
        id="STREAK_30_DAYS",
        title="30-Day Streak",
        description="Maintain a 30-day learning streak.",
        criterion_kind=CRITERION_STREAK_N_DAYS,
        criterion_value={"days": 30},
        rarity="EPIC",
        icon="🔥",
        xp_reward=200,
    ),
    Achievement(
        id="LEVEL_25",
        title="Level 25",
        description="Reach level 25.",
        criterion_kind=CRITERION_LEVEL_N,
        criterion_value={"level": 25},
        rarity="EPIC",
        icon="💎",
        xp_reward=250,
    ),
]


# --- Batch 3 achievements (gamification + social) ---------------------------

CRITERION_DAILY_GOAL_N = "DAILY_GOAL_N"
CRITERION_TOURNAMENT_WINNER = "TOURNAMENT_WINNER"

BATCH3_ACHIEVEMENTS: list[Achievement] = [
    Achievement(
        id="DAILY_GOAL_7",
        title="Weekly Warrior",
        description="Complete your daily goal 7 days in a row.",
        criterion_kind=CRITERION_DAILY_GOAL_N,
        criterion_value={"days": 7},
        rarity="RARE",
        icon="🎯",
        xp_reward=75,
    ),
    Achievement(
        id="DAILY_GOAL_30",
        title="Monthly Champion",
        description="Complete your daily goal 30 days in a row.",
        criterion_kind=CRITERION_DAILY_GOAL_N,
        criterion_value={"days": 30},
        rarity="EPIC",
        icon="🏅",
        xp_reward=300,
    ),
    Achievement(
        id="TOURNAMENT_WINNER",
        title="Tournament Victor",
        description="Win a tournament.",
        criterion_kind=CRITERION_TOURNAMENT_WINNER,
        criterion_value={},
        rarity="LEGENDARY",
        icon="👑",
        xp_reward=500,
    ),
]


def _seed_list(
    repo: AchievementRepository, defs: list[Achievement]
) -> None:
    """Upsert each definition. Detached helper for re-use across both lists."""
    for definition in defs:
        # Build a fresh ORM instance per upsert so a re-run isn't trying
        # to re-insert an already-attached object from a prior call.
        fresh = Achievement(
            id=definition.id,
            title=definition.title,
            description=definition.description,
            criterion_kind=definition.criterion_kind,
            criterion_value=definition.criterion_value,
            rarity=definition.rarity,
            icon=definition.icon,
            xp_reward=definition.xp_reward,
        )
        repo.upsert_achievement(fresh)


def seed_mvp_achievements(repo: AchievementRepository) -> None:
    """Write :data:`MVP_ACHIEVEMENTS`. Idempotent on re-runs."""
    _seed_list(repo, MVP_ACHIEVEMENTS)


def seed_phase2_achievements(repo: AchievementRepository) -> None:
    """Write :data:`PHASE2_ACHIEVEMENTS`. Idempotent on re-runs."""
    _seed_list(repo, PHASE2_ACHIEVEMENTS)


def seed_batch3_achievements(repo: AchievementRepository) -> None:
    """Write :data:`BATCH3_ACHIEVEMENTS`. Idempotent on re-runs."""
    _seed_list(repo, BATCH3_ACHIEVEMENTS)


def seed_all_achievements(repo: AchievementRepository) -> None:
    """Write MVP, Phase 2, and Batch 3 sets. Idempotent on re-runs."""
    seed_mvp_achievements(repo)
    seed_phase2_achievements(repo)
    seed_batch3_achievements(repo)
