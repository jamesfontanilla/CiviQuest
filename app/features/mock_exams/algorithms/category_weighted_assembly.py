"""Category-weighted mock-exam assembly (Task 12.3, design A1).

Pure-ish helper that takes per-module pools and per-module weights and
returns the assembled list of questions plus the audit seed. Mirrors the
quizzes-slice ``assemble_quiz`` but with the weighting wrinkle: each
module contributes a configured number of questions, and the final
list is shuffled across modules so the learner doesn't see all of one
module's questions before the next.

What is here:

1. **Per-module sample.** For each ``module_id_str`` in ``weights``,
   walk to the matching pool in ``pools_by_module`` and draw exactly
   ``count`` questions via :func:`rng.sample`. If any pool is short,
   raise 409 ``insufficient_question_pool`` so the router surface
   matches the design's error catalog (Req 10.1, 10.2, 18.4).
2. **Cross-module shuffle.** ``rng.shuffle`` is applied to the merged
   list so adjacency by module is destroyed. The final ordering is
   what the learner sees.
3. **64-bit audit seed.** ``rng.randbits(64)`` captured at the end so
   ``mock_exam_attempts.seed`` carries a reproducible signature
   (Req 21).

What is **not** here:

- **Per-question option shuffling.** That mutation has to happen at
  the service layer where each ``Question`` row is being projected
  into the ``MockExamAttemptAnswer`` row — the same reasoning as in
  :mod:`app.features.quizzes.algorithms.assembly`.
- **Pool fetching.** The service fetches pools via
  ``QuestionRepository.list_active_passing_quality_gate(module_id=...,
  category=...)`` per module. The quality gate is already applied;
  this function takes the result.

The seed return shape ``(chosen, seed)`` matches the quizzes assembler so
both call sites can be threaded through the same persistence helper if
later refactors merge them.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.features.content.models import Question
from app.infrastructure.security import rng


def assemble_mock_exam(
    *,
    weights: dict[str, int],
    pools_by_module: dict[int, list[Question]],
) -> tuple[list[Question], int]:
    """Sample a category-weighted question list and return ``(chosen, seed)``.

    Args:
        weights: mapping ``str(module_id) -> count``. The keys are
            string-typed because ``MockExamConfig.weights_json`` is a
            JSON dict (and JSON dicts can't have integer keys on the
            wire). The function casts to ``int`` when looking up the
            matching pool.
        pools_by_module: mapping ``int(module_id) -> list[Question]``,
            with the quality gate already applied. The caller (service)
            is responsible for filtering by the user's category and the
            ``is_active`` / quality predicates.

    Returns:
        A pair ``(chosen, seed)``. ``chosen`` is a fresh list (does not
        alias any input pool); its length equals ``sum(weights.values())``.
        ``seed`` is a non-negative 64-bit integer captured for audit
        (Req 21).

    Raises:
        HTTPException: 409 ``insufficient_question_pool`` when any
        module's pool is smaller than its configured weight.
    """
    chosen: list[Question] = []

    for module_id_str, count in weights.items():
        module_id = int(module_id_str)
        pool = pools_by_module.get(module_id, [])
        if len(pool) < count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="insufficient_question_pool",
            )
        chosen.extend(rng.sample(pool, count))

    # Cross-module shuffle so the learner's ordering is not "all of
    # module 1, then all of module 2, ...". Randomisation is
    # in-place on the local list; the caller's pools are untouched.
    rng.shuffle(chosen)

    seed = rng.randbits(63)  # 63 bits to stay within SQLite signed INTEGER max
    return chosen, seed
