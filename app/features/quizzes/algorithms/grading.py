"""Quiz grading algorithm (Task 11.3, design A2 + Req 7.5).

Pure-function grading: take the answered :class:`QuizAttemptAnswer`
rows and the ``Question`` lookup, return per-question correctness plus
aggregate score / pass / perfect flags.

The grading function is intentionally separate from
:meth:`QuizRepository.submit_attempt` because:

- It's deterministic and pure, which makes it the natural surface for
  property tests of Req 7.5.
- The service layer threads the result into both the persistence path
  (``answer_corrections`` for ``submit_attempt``) and the response
  shape (``QuizSubmittedResponse.questions``) — having one source of
  truth keeps those two paths in lockstep.

Pass thresholds:
- Subtopic perfection (Req 7.6): ``score == max_score`` and the
  ``QUIZ_PERFECT`` XP source applies (50 XP).
- Subtopic non-perfect pass (Req 7.7): ``percentage >= 0.80`` →
  ``QUIZ_PASS`` (20 XP).
- Topic / module pass (Req 8.4 / 9.4): ``percentage >= 0.80`` →
  ``QUIZ_PASS`` at the topic-/module-specific amount (set by the
  service, not here).

Both ``is_perfect`` and ``is_passing`` are returned so the service can
decide which XP source applies without re-doing the arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.features.content.models import Question
from app.features.quizzes.models import QuizAttemptAnswer


# Req 7.7 / 8.4 / 9.4 — 80% threshold for non-perfect pass.
PASS_THRESHOLD_PCT: float = 0.80


@dataclass
class GradedAnswer:
    """One question's grading record (Req 7.5).

    Carries every field the submitted-attempt response shape needs
    (``QuizGradedQuestion`` mirrors this in ``schemas.py``). The
    service projects ``GradedAnswer`` straight into both the
    persistence write and the wire response.
    """

    question_id: int
    ordinal: int
    selected_answer: str | None
    correct_answer: str
    is_correct: bool
    explanation: str


@dataclass
class GradeResult:
    """Aggregate grading for a whole attempt."""

    answers: list[GradedAnswer]
    score: int
    max_score: int
    percentage: float
    is_perfect: bool
    is_passing: bool


def grade_attempt(
    *,
    attempt_answers: list[QuizAttemptAnswer],
    question_lookup: dict[int, Question],
) -> GradeResult:
    """Grade a fully-answered attempt.

    Args:
        attempt_answers: The persisted answer rows for the attempt.
            Each row's ``selected_answer`` is read; rows with ``None``
            count as incorrect (a learner who skipped a question loses
            that point).
        question_lookup: Mapping ``question_id -> Question`` for every
            question on the attempt. The service builds this once
            from the attempt's answer rows so the grader can do a
            single dict lookup per question without a DB round trip.

    Returns:
        A :class:`GradeResult` with every per-question record plus
        the aggregate score / max / percentage / flags. ``score`` is
        the count of ``is_correct`` rows; ``max_score`` is
        ``len(attempt_answers)`` (the assembled count, not the
        answered count — Req 7.5 grades over the full assembled set).

    Edge cases:
        - An attempt with no answers ``max_score == 0``. Returns
          ``percentage = 0.0``, ``is_perfect = False``, ``is_passing
          = False``. The service's start-quiz path makes this
          impossible (assembly always produces N>0), but the function
          stays total for safety.
    """
    graded: list[GradedAnswer] = []
    for answer in attempt_answers:
        question = question_lookup.get(answer.question_id)
        if question is None:
            # A missing question id in the lookup means the service
            # built the dict from a stale snapshot. Treating this as
            # "skip" rather than raising keeps the grader pure; the
            # service's own invariant should prevent it from happening.
            graded.append(
                GradedAnswer(
                    question_id=answer.question_id,
                    ordinal=answer.ordinal,
                    selected_answer=answer.selected_answer,
                    correct_answer="",
                    is_correct=False,
                    explanation="",
                )
            )
            continue

        is_correct = (
            answer.selected_answer is not None
            and answer.selected_answer == question.correct_answer
        )
        graded.append(
            GradedAnswer(
                question_id=answer.question_id,
                ordinal=answer.ordinal,
                selected_answer=answer.selected_answer,
                correct_answer=question.correct_answer,
                is_correct=is_correct,
                explanation=question.explanation,
            )
        )

    score = sum(1 for g in graded if g.is_correct)
    max_score = len(graded)
    percentage = score / max_score if max_score > 0 else 0.0
    is_perfect = max_score > 0 and score == max_score
    is_passing = max_score > 0 and percentage >= PASS_THRESHOLD_PCT

    return GradeResult(
        answers=graded,
        score=score,
        max_score=max_score,
        percentage=percentage,
        is_perfect=is_perfect,
        is_passing=is_passing,
    )
