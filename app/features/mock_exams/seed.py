"""Phase 2 mock-exam config seed (Task 13.1).

Phase 2 lifts the mock-exam length from the MVP's 50 questions to the
CSC-published 165 (Req 10.1, 10.2). The official per-module weights
that should sum to 165 are not part of the project corpus, so this
module distributes the 165 slots across the supplied modules **as
evenly as possible** with deterministic remainder placement on the
lowest-index modules. The admin write surface (Task 17.x) is the
intended override path once the official weights are wired in.

Why this lives in its own module rather than on
:class:`MockExamService`:

- The service is the request-time façade. Seed work happens at
  bootstrap (Task 22.2) and from the future admin tool — neither has
  a request user, neither needs the service's grading / timer
  surface, and both want a single transactional ``upsert`` per
  category. Splitting the loader out keeps the service free of
  bootstrap-only branches.
- The function is repository-driven on purpose. The repository's
  :meth:`MockExamRepository.upsert_config` already handles the
  insert-or-update collapse, so a seeder that calls it twice with
  the same input produces the same row state — that's the
  idempotency the bootstrap caller depends on.

Why the weight distribution is deterministic:

- Bootstrap and the test suite both want byte-stable output for the
  same inputs. Picking remainder placement at random would produce
  flaky migration diffs without buying anything.
- "Lowest-index modules get the +1" is a defensible convention: in
  the seed loader the module list is in module-creation order, so
  the +1 lands on the modules a learner sees first. When the admin
  tool replaces these weights with CSC-published values, this
  ordering becomes irrelevant.

Module call sites:

- ``scripts/seed.py`` (Task 22.2) — bootstrap loader; passes the
  two category lists from the seeded fixtures.
- Future admin tool (Task 17.x) — initial config write before the
  CSC weights override is keyed in. The function is intentionally
  thin so the admin write surface can call it once and then patch
  the weights via :meth:`MockExamRepository.upsert_config` directly.
"""

from __future__ import annotations

from app.features.mock_exams.models import MockExamNavPolicy
from app.features.mock_exams.repository import MockExamRepository
from app.features.users.models import Category


PHASE2_TOTAL_QUESTIONS = 165
"""Total mock-exam length under Phase 2 (Req 10.1, 10.2)."""

PHASE2_TIME_LIMIT_MINUTES = 180
"""Default per-attempt time limit (design `mock_exam_configs` row)."""

PHASE2_PASS_THRESHOLD = 0.80
"""Default pass threshold (design Req 10.5 / 10.7)."""


def compute_phase2_weights(module_ids: list[int]) -> dict[str, int]:
    """Distribute :data:`PHASE2_TOTAL_QUESTIONS` evenly over the modules.

    The remainder ``PHASE2_TOTAL_QUESTIONS % len(module_ids)`` is
    placed on the *first* ``remainder`` modules in the supplied list
    (the lowest-index modules), one extra each. The output is
    string-keyed because :class:`~app.features.mock_exams.models.MockExamConfig`
    persists ``weights_json`` as JSON, and JSON dicts can't have integer
    keys on the wire.

    Args:
        module_ids: ordered list of module ids to spread the 165
            slots across. Must be non-empty.

    Returns:
        A mapping ``str(module_id) -> int(count)`` whose values sum
        exactly to :data:`PHASE2_TOTAL_QUESTIONS`.

    Raises:
        ValueError: when ``module_ids`` is empty.

    Examples:
        >>> compute_phase2_weights([1, 2, 3, 4, 5])
        {'1': 33, '2': 33, '3': 33, '4': 33, '5': 33}
        >>> compute_phase2_weights([10, 20, 30, 40, 50, 60, 70])
        {'10': 24, '20': 24, '30': 24, '40': 24, '50': 23, '60': 23, '70': 23}
        >>> compute_phase2_weights([42])
        {'42': 165}
        >>> sum(compute_phase2_weights([1, 2, 3, 4, 5, 6, 7]).values())
        165
    """
    if not module_ids:
        raise ValueError("at least one module required for Phase 2 seed")

    n = len(module_ids)
    base, remainder = divmod(PHASE2_TOTAL_QUESTIONS, n)

    weights: dict[str, int] = {}
    for index, module_id in enumerate(module_ids):
        bonus = 1 if index < remainder else 0
        weights[str(module_id)] = base + bonus
    return weights


def seed_phase2_configs(
    repo: MockExamRepository,
    *,
    module_ids_by_category: dict[Category, list[int]],
) -> None:
    """Seed (or upsert) Phase 2 mock-exam configs for each category.

    For each ``(category, module_ids)`` pair, computes a weights
    dictionary via :func:`compute_phase2_weights` and writes it
    through :meth:`MockExamRepository.upsert_config` along with the
    Phase 2 defaults: ``total_questions=165``,
    ``time_limit_minutes=180``, ``nav_policy=LINEAR_NO_REVISIT``,
    ``pass_threshold=0.80``.

    The function is idempotent — calling it twice with the same input
    yields byte-identical config rows because ``upsert_config``
    overwrites every value field on the existing row.

    Args:
        repo: persistence boundary for the mock-exam slice.
        module_ids_by_category: mapping from CSE category to the list
            of module ids over which the 165 slots should be
            distributed. Each list must be non-empty; an empty list
            triggers the Phase-2-required-modules guard inside
            :func:`compute_phase2_weights`.

    Raises:
        ValueError: when any category's module list is empty.
    """
    for category, module_ids in module_ids_by_category.items():
        weights = compute_phase2_weights(module_ids)
        repo.upsert_config(
            category=category,
            total_questions=PHASE2_TOTAL_QUESTIONS,
            weights_json=weights,
            time_limit_minutes=PHASE2_TIME_LIMIT_MINUTES,
            nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
            pass_threshold=PHASE2_PASS_THRESHOLD,
        )
