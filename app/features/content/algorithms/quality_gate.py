"""Quality-gate predicate for question assembly (Req 18.1, 18.2, 18.3, 18.4).

The gate has two halves intentionally:

1. ``valid_question_filter()`` — a SQLAlchemy boolean expression that is
   AND-ed into every ``select(Question)`` used by an assembler. It enforces
   the type-agnostic rules: ``is_active``, non-empty ``stem``,
   non-empty ``explanation``, non-empty ``correct_answer``, and closed-set
   membership for ``difficulty`` and ``qtype``.

2. ``is_question_quality_passing(q)`` — a Python helper that completes the
   check by looking inside the JSON ``options`` column and running the
   MC/IDENTIFICATION-specific rules (option count 2..6,
   ``correct_answer in options``).

Why split them?

SQLite's JSON support is real but inconsistent across SQLAlchemy versions
when used as a portable expression — ``json_array_length`` works under one
typing of the column, ``json_each`` is awkward to combine with the rest of
the predicate, and we'd be writing dialect-specific SQL inside a feature's
algorithm module. Doing the JSON-aware checks in Python costs us a bounded
post-filter (the SQL gate already removes the bulk of bad rows), keeps the
predicate portable to Postgres later, and gives the read-side and the
write-side a single shared rule book.

Rule strings returned by ``is_question_quality_passing`` align with
``QuestionRejectionLog.rule`` so the service can log a rejection (Req 18.4)
without an additional mapping table.
"""

from __future__ import annotations

from sqlalchemy import and_, func

from app.features.content.models import Difficulty, Question, QuestionType


# Rule strings — mirrored to ``QuestionRejectionLog.rule`` (Req 18.4).
RULE_STEM_EMPTY = "Q_STEM_EMPTY"
RULE_NO_CORRECT_ANSWER = "Q_NO_CORRECT_ANSWER"
RULE_EMPTY_EXPLANATION = "Q_EMPTY_EXPLANATION"
RULE_INVALID_DIFFICULTY = "Q_INVALID_DIFFICULTY"
RULE_INVALID_TYPE = "Q_INVALID_TYPE"
RULE_MC_OPTION_COUNT = "Q_MC_OPTION_COUNT"
RULE_CORRECT_NOT_IN_OPTIONS = "Q_CORRECT_NOT_IN_OPTIONS"


def valid_question_filter():
    """Return a SQLAlchemy boolean expression for the type-agnostic gate.

    Use as::

        stmt = select(Question).where(valid_question_filter())

    The expression handles every Req 18.1 rule that does not require
    parsing the JSON ``options`` column. The repository's
    ``list_active_passing_quality_gate`` post-filters with
    :func:`is_question_quality_passing` to enforce the JSON-aware rules
    (Req 18.2 option count, Req 18.3 ``correct_answer in options``).
    """
    return and_(
        Question.is_active.is_(True),
        Question.stem.isnot(None),
        func.length(func.trim(Question.stem)) > 0,
        Question.explanation.isnot(None),
        func.length(func.trim(Question.explanation)) > 0,
        Question.correct_answer.isnot(None),
        func.length(func.trim(Question.correct_answer)) > 0,
        Question.difficulty.in_([d.value for d in Difficulty]),
        Question.qtype.in_([q.value for q in QuestionType]),
    )


def _coerce_options(raw: object) -> list | None:
    """Normalise the ``options`` column read-back into a Python list.

    SQLAlchemy's ``JSON`` type returns parsed Python objects on engines with
    JSON support (SQLite with json1, Postgres). Some legacy rows or odd
    drivers may hand back the raw string; defensive parsing keeps the
    helper tolerant.
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        # Lazy import json so the hot path (already-parsed list) stays cheap.
        import json

        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, list) else None
    return None


def is_question_quality_passing(q: Question) -> tuple[bool, str | None]:
    """Apply the full quality gate to a single ``Question`` ORM row.

    Returns ``(True, None)`` when the question is fit to serve, or
    ``(False, RULE_*)`` naming the first rule violated. Rule check order
    matches the Req 18.1/18.2/18.3 narrative order so the failure surface
    is predictable.

    Used by:

    - ``QuestionRepository.list_active_passing_quality_gate`` to post-filter
      after the SQL gate.
    - The content service's admin-write path to derive the
      ``question_rejection_log.rule`` string for Req 18.4.
    """
    if q.stem is None or not str(q.stem).strip():
        return False, RULE_STEM_EMPTY
    if q.correct_answer is None or not str(q.correct_answer).strip():
        return False, RULE_NO_CORRECT_ANSWER
    if q.explanation is None or not str(q.explanation).strip():
        return False, RULE_EMPTY_EXPLANATION
    if q.difficulty not in {d.value for d in Difficulty}:
        return False, RULE_INVALID_DIFFICULTY
    if q.qtype not in {qt.value for qt in QuestionType}:
        return False, RULE_INVALID_TYPE

    options = _coerce_options(q.options)

    if q.qtype == QuestionType.MULTIPLE_CHOICE.value:
        # Req 18.2: MC must have 2..6 options.
        if options is None or not (2 <= len(options) <= 6):
            return False, RULE_MC_OPTION_COUNT
        # Req 18.3: MC correct_answer must match an option.
        if q.correct_answer not in options:
            return False, RULE_CORRECT_NOT_IN_OPTIONS
        return True, None

    if q.qtype == QuestionType.IDENTIFICATION.value:
        # Req 18.3 covers IDENTIFICATION when options are provided. If no
        # options column, identification is free-text and we let it through.
        if options is not None and q.correct_answer not in options:
            return False, RULE_CORRECT_NOT_IN_OPTIONS
        return True, None

    # Other qtypes have no Req 18.2 / 18.3 obligations. If options are
    # provided, treat them like IDENTIFICATION for consistency.
    if options is not None and q.correct_answer not in options:
        return False, RULE_CORRECT_NOT_IN_OPTIONS

    return True, None
