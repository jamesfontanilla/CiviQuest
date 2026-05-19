"""Quiz assembly algorithm (Task 11.2, design A2).

The assembler is a thin pure-ish function: given a pre-filtered question
pool and a scope, return the sampled subset and the seed used. The pool
is provided by the caller (the service layer) via
``QuestionRepository.list_active_passing_quality_gate(...)`` so the
quality gate (Req 18) is already applied.

Two responsibilities live here:

1. **Count enforcement.** ``COUNT_BY_SCOPE`` pins the per-scope size
   per Req 7.1, 8.2, 9.2. If the pool is smaller, raise the canonical
   409 ``insufficient_question_pool`` error so the router surface
   matches the design's error catalog.
2. **Randomization.** Use the security RNG (``rng.sample``) to draw
   the subset and ``rng.randbits(64)`` to capture the seed for audit.

What is **not** here:

- **Per-question option shuffling.** That mutation needs to happen at
  the service layer where each ``Question`` row is being projected
  into the ``QuizAttemptAnswer`` table. Mutating the ORM rows here
  would corrupt the identity map (the same ``Question`` object would
  carry attempt-specific state) and bleed into other reads.
- **Persistence.** This module returns Python objects only; the
  service layer wires the assembly into ``QuizRepository.create_attempt``
  + ``add_attempt_questions``.

The design's wording ("rng_seed" parameter) is satisfied here by
returning the seed alongside the question list — callers store it on
the ``QuizAttempt`` row for audit reproducibility (Req 21). We do not
take ``rng_seed`` as a parameter because the security RNG is
non-deterministic by design; reproduction tooling outside the request
path can rebuild the population from the seed.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.features.content.models import LevelScope, Question
from app.infrastructure.security import rng


# Req 7.1 (subtopic = 20), 8.2 (topic = 50), 9.2 (module = 100).
COUNT_BY_SCOPE: dict[LevelScope, int] = {
    LevelScope.SUBTOPIC: 20,
    LevelScope.TOPIC: 50,
    LevelScope.MODULE: 100,
}


def assemble_quiz(
    *,
    scope_level: LevelScope,
    pool: list[Question],
) -> tuple[list[Question], int]:
    """Sample a per-scope subset from ``pool`` and return ``(subset, seed)``.

    Steps:

    1. Look up the per-scope target count from :data:`COUNT_BY_SCOPE`.
       ``LevelScope.SUBTOPIC = 20``, ``TOPIC = 50``, ``MODULE = 100``.
    2. If the pool is smaller than the target, raise
       :class:`HTTPException` 409 ``insufficient_question_pool``.
       Surfaces directly to the client per the design's error catalog.
    3. Capture a 64-bit audit seed via ``rng.randbits``. Returned
       alongside the subset so the service can persist it on the
       attempt row.
    4. Use ``rng.sample`` (security CSPRNG) to draw the subset. Order
       returned by ``sample`` is itself random — callers can use the
       returned ordering directly as the display order.

    Returns:
        A pair ``(subset, seed)``. ``subset`` is a fresh list (does not
        alias ``pool``). ``seed`` is a non-negative 64-bit integer.

    Raises:
        HTTPException: 409 ``insufficient_question_pool`` when
        ``len(pool) < COUNT_BY_SCOPE[scope_level]``.

    The ``scope_id`` argument from the design's signature is omitted —
    the pool is already scope-filtered by the caller, so the algorithm
    has no further use for the id. The service layer keeps it on the
    attempt row.
    """
    target = COUNT_BY_SCOPE[scope_level]
    if len(pool) < target:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="insufficient_question_pool",
        )

    seed = rng.randbits(63)  # 63 bits to stay within SQLite signed INTEGER max
    chosen = rng.sample(pool, target)
    return chosen, seed
