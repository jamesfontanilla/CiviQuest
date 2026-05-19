"""Repository tests for the quizzes slice (Task 11.1).

Exercises :class:`QuizRepository` against in-memory SQLite — no mocks,
per ``testing-standards.md``. Each test seeds a real
``User -> Module -> Topic -> Subtopic -> Question`` chain so foreign-key
constraints are honoured.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.content.models import (
    Difficulty,
    LevelScope,
    Module,
    Question,
    QuestionType,
    Subtopic,
    Topic,
)
from app.features.quizzes.models import QuizAttemptStatus
from app.features.quizzes.repository import QuizRepository
from app.features.users.models import Category
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate


# --- factories --------------------------------------------------------------


def _make_user(
    db: Session, *, email: str = "alice@example.com"
) -> object:
    repo = UserRepository(db=db)
    return repo.create(
        UserCreate(
            email=email,
            display_name="Alice",
            age=25,
            category=Category.PROFESSIONAL.value,
            password="Strong1Pass!",
        ),
        password_hash="bcrypt$fake$hash",
    )


def _seed_subtopic_with_questions(
    db: Session, *, count: int = 3, slug_prefix: str = "s"
) -> tuple[Subtopic, list[Question]]:
    module = Module(
        category=Category.PROFESSIONAL.value,
        slug=f"m-{slug_prefix}",
        title="M",
        order_index=0,
    )
    db.add(module)
    db.commit()
    db.refresh(module)
    topic = Topic(
        module_id=module.id,
        slug=f"t-{slug_prefix}",
        title="T",
        order_index=0,
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    subtopic = Subtopic(
        topic_id=topic.id,
        slug=f"sub-{slug_prefix}",
        title="S",
        order_index=0,
    )
    db.add(subtopic)
    db.commit()
    db.refresh(subtopic)
    questions: list[Question] = []
    for i in range(count):
        q = Question(
            subtopic_id=subtopic.id,
            topic_id=topic.id,
            module_id=module.id,
            category=Category.PROFESSIONAL.value,
            level_scope=LevelScope.SUBTOPIC.value,
            stem=f"Q{i}?",
            options=["A", "B", "C", "D"],
            correct_answer="A",
            explanation="exp",
            difficulty=Difficulty.EASY.value,
            qtype=QuestionType.MULTIPLE_CHOICE.value,
            is_active=True,
        )
        db.add(q)
        db.commit()
        db.refresh(q)
        questions.append(q)
    return subtopic, questions


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# --- create_attempt ---------------------------------------------------------


def test_create_attempt_persists_all_fields(db_session: Session) -> None:
    user = _make_user(db_session)
    subtopic, _ = _seed_subtopic_with_questions(db_session)
    repo = QuizRepository(db=db_session)
    when = _now()

    attempt = repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=when,
        max_score=20,
        seed=123456789,
        client_event_id="evt-1",
    )

    assert attempt.id is not None
    assert attempt.user_id == user.id
    assert attempt.scope_level == LevelScope.SUBTOPIC.value
    assert attempt.scope_id == subtopic.id
    assert attempt.status == QuizAttemptStatus.IN_PROGRESS.value
    assert attempt.max_score == 20
    assert attempt.seed == 123456789
    assert attempt.client_event_id == "evt-1"
    assert attempt.score is None
    assert attempt.submitted_at is None


def test_create_attempt_unique_client_event_id(db_session: Session) -> None:
    user = _make_user(db_session)
    subtopic, _ = _seed_subtopic_with_questions(db_session)
    repo = QuizRepository(db=db_session)
    when = _now()

    repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=when,
        max_score=20,
        seed=1,
        client_event_id="dup",
    )
    with pytest.raises(IntegrityError):
        repo.create_attempt(
            user_id=user.id,
            scope_level=LevelScope.SUBTOPIC,
            scope_id=subtopic.id,
            started_at=when,
            max_score=20,
            seed=2,
            client_event_id="dup",
        )
    db_session.rollback()


# --- get_attempt / get_attempt_for_user ------------------------------------


def test_get_attempt_returns_row_or_none(db_session: Session) -> None:
    user = _make_user(db_session)
    subtopic, _ = _seed_subtopic_with_questions(db_session)
    repo = QuizRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=20,
        seed=1,
    )

    assert repo.get_attempt(a.id) is not None
    assert repo.get_attempt(99999) is None


def test_get_attempt_for_user_authorizes_owner(db_session: Session) -> None:
    alice = _make_user(db_session)
    bob = _make_user(db_session, email="bob@example.com")
    subtopic, _ = _seed_subtopic_with_questions(db_session)
    repo = QuizRepository(db=db_session)
    a = repo.create_attempt(
        user_id=alice.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=20,
        seed=1,
    )

    assert repo.get_attempt_for_user(a.id, alice.id) is not None
    # Bob's id does not own the attempt — repo returns None so the service
    # can raise a uniform 403.
    assert repo.get_attempt_for_user(a.id, bob.id) is None


# --- get_in_progress_attempts ----------------------------------------------


def test_get_in_progress_attempts_filters_by_user_and_status(
    db_session: Session,
) -> None:
    alice = _make_user(db_session)
    bob = _make_user(db_session, email="bob@example.com")
    subtopic, _ = _seed_subtopic_with_questions(db_session)
    repo = QuizRepository(db=db_session)

    in_progress = repo.create_attempt(
        user_id=alice.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=20,
        seed=1,
    )
    repo.create_attempt(
        user_id=bob.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=20,
        seed=2,
    )

    rows = repo.get_in_progress_attempts(alice.id)
    assert len(rows) == 1
    assert rows[0].id == in_progress.id


def test_get_in_progress_attempts_excludes_submitted(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    subtopic, questions = _seed_subtopic_with_questions(db_session, count=1)
    repo = QuizRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=1,
        seed=1,
    )
    repo.add_attempt_questions(
        a.id,
        rows=[
            {
                "question_id": questions[0].id,
                "ordinal": 1,
                "displayed_options": ["A", "B", "C", "D"],
            }
        ],
    )
    repo.submit_attempt(
        a.id,
        score=1,
        submitted_at=_now(),
        answer_corrections=[
            {"question_id": questions[0].id, "is_correct": True}
        ],
    )

    assert repo.get_in_progress_attempts(user.id) == []


# --- get_by_client_event_id ------------------------------------------------


def test_get_by_client_event_id_returns_row_or_none(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    subtopic, _ = _seed_subtopic_with_questions(db_session)
    repo = QuizRepository(db=db_session)

    assert repo.get_by_client_event_id("missing") is None

    a = repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=20,
        seed=1,
        client_event_id="evt-find-me",
    )
    found = repo.get_by_client_event_id("evt-find-me")
    assert found is not None
    assert found.id == a.id


# --- add_attempt_questions / list_attempt_answers --------------------------


def test_add_attempt_questions_inserts_all_rows(db_session: Session) -> None:
    user = _make_user(db_session)
    subtopic, questions = _seed_subtopic_with_questions(db_session, count=3)
    repo = QuizRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=3,
        seed=1,
    )

    repo.add_attempt_questions(
        a.id,
        rows=[
            {
                "question_id": q.id,
                "ordinal": i + 1,
                "displayed_options": ["A", "B", "C", "D"],
            }
            for i, q in enumerate(questions)
        ],
    )

    listed = repo.list_attempt_answers(a.id)
    assert [r.ordinal for r in listed] == [1, 2, 3]
    assert {r.question_id for r in listed} == {q.id for q in questions}
    # Pre-answer fields are NULL.
    for r in listed:
        assert r.selected_answer is None
        assert r.is_correct is None
        assert r.answered_at is None
        assert r.displayed_options == ["A", "B", "C", "D"]


def test_add_attempt_questions_unique_ordinal_violation(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    subtopic, questions = _seed_subtopic_with_questions(db_session, count=2)
    repo = QuizRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=2,
        seed=1,
    )

    with pytest.raises(IntegrityError):
        repo.add_attempt_questions(
            a.id,
            rows=[
                {"question_id": questions[0].id, "ordinal": 1},
                {"question_id": questions[1].id, "ordinal": 1},
            ],
        )
    db_session.rollback()


def test_add_attempt_questions_unique_question_violation(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    subtopic, questions = _seed_subtopic_with_questions(db_session, count=2)
    repo = QuizRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=2,
        seed=1,
    )

    with pytest.raises(IntegrityError):
        repo.add_attempt_questions(
            a.id,
            rows=[
                {"question_id": questions[0].id, "ordinal": 1},
                {"question_id": questions[0].id, "ordinal": 2},
            ],
        )
    db_session.rollback()


# --- set_answer (upsert semantics) ------------------------------------------


def test_set_answer_updates_existing_row(db_session: Session) -> None:
    user = _make_user(db_session)
    subtopic, questions = _seed_subtopic_with_questions(db_session, count=1)
    repo = QuizRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=1,
        seed=1,
    )
    repo.add_attempt_questions(
        a.id,
        rows=[{"question_id": questions[0].id, "ordinal": 1}],
    )

    when = _now()
    row = repo.set_answer(
        attempt_id=a.id,
        question_id=questions[0].id,
        selected_answer="A",
        answered_at=when,
    )

    assert row.selected_answer == "A"
    # is_correct must remain None — grading happens at submit only.
    assert row.is_correct is None
    assert row.answered_at is not None


def test_set_answer_overwrites_prior_selection(db_session: Session) -> None:
    user = _make_user(db_session)
    subtopic, questions = _seed_subtopic_with_questions(db_session, count=1)
    repo = QuizRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=1,
        seed=1,
    )
    repo.add_attempt_questions(
        a.id,
        rows=[{"question_id": questions[0].id, "ordinal": 1}],
    )

    repo.set_answer(
        attempt_id=a.id,
        question_id=questions[0].id,
        selected_answer="A",
        answered_at=_now(),
    )
    repo.set_answer(
        attempt_id=a.id,
        question_id=questions[0].id,
        selected_answer="B",
        answered_at=_now(),
    )

    listed = repo.list_attempt_answers(a.id)
    assert listed[0].selected_answer == "B"


def test_set_answer_raises_for_unknown_pair(db_session: Session) -> None:
    user = _make_user(db_session)
    subtopic, _ = _seed_subtopic_with_questions(db_session, count=1)
    repo = QuizRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=1,
        seed=1,
    )

    with pytest.raises(LookupError):
        repo.set_answer(
            attempt_id=a.id,
            question_id=99999,
            selected_answer="A",
            answered_at=_now(),
        )


# --- submit_attempt ---------------------------------------------------------


def test_submit_attempt_persists_score_and_corrections(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    subtopic, questions = _seed_subtopic_with_questions(db_session, count=2)
    repo = QuizRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=2,
        seed=1,
    )
    repo.add_attempt_questions(
        a.id,
        rows=[
            {"question_id": questions[0].id, "ordinal": 1},
            {"question_id": questions[1].id, "ordinal": 2},
        ],
    )

    when = _now()
    submitted = repo.submit_attempt(
        a.id,
        score=1,
        submitted_at=when,
        answer_corrections=[
            {"question_id": questions[0].id, "is_correct": True},
            {"question_id": questions[1].id, "is_correct": False},
        ],
    )

    assert submitted.status == QuizAttemptStatus.SUBMITTED.value
    assert submitted.score == 1
    assert submitted.submitted_at is not None

    rows = repo.list_attempt_answers(a.id)
    by_qid = {r.question_id: r for r in rows}
    assert by_qid[questions[0].id].is_correct is True
    assert by_qid[questions[1].id].is_correct is False


def test_submit_attempt_raises_for_missing_attempt(
    db_session: Session,
) -> None:
    repo = QuizRepository(db=db_session)
    with pytest.raises(LookupError):
        repo.submit_attempt(
            99999,
            score=0,
            submitted_at=_now(),
            answer_corrections=[],
        )


# --- has_passed_attempt -----------------------------------------------------


def test_has_passed_attempt_threshold_exact_at_80pct(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    subtopic, questions = _seed_subtopic_with_questions(db_session, count=1)
    repo = QuizRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=10,
        seed=1,
    )
    repo.add_attempt_questions(
        a.id,
        rows=[{"question_id": questions[0].id, "ordinal": 1}],
    )
    repo.submit_attempt(
        a.id,
        score=8,
        submitted_at=_now(),
        answer_corrections=[
            {"question_id": questions[0].id, "is_correct": True}
        ],
    )

    assert repo.has_passed_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
    ) is True


def test_has_passed_attempt_below_threshold(db_session: Session) -> None:
    user = _make_user(db_session)
    subtopic, questions = _seed_subtopic_with_questions(db_session, count=1)
    repo = QuizRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=10,
        seed=1,
    )
    repo.add_attempt_questions(
        a.id,
        rows=[{"question_id": questions[0].id, "ordinal": 1}],
    )
    repo.submit_attempt(
        a.id,
        score=7,
        submitted_at=_now(),
        answer_corrections=[
            {"question_id": questions[0].id, "is_correct": True}
        ],
    )

    assert repo.has_passed_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
    ) is False


def test_has_passed_attempt_ignores_in_progress(db_session: Session) -> None:
    user = _make_user(db_session)
    subtopic, _ = _seed_subtopic_with_questions(db_session)
    repo = QuizRepository(db=db_session)
    repo.create_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
        started_at=_now(),
        max_score=10,
        seed=1,
    )

    # In-progress attempt has no score yet — must not count as "passed".
    assert repo.has_passed_attempt(
        user_id=user.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=subtopic.id,
    ) is False


def test_has_passed_attempt_isolated_per_user_and_scope(
    db_session: Session,
) -> None:
    alice = _make_user(db_session)
    bob = _make_user(db_session, email="bob@example.com")
    sub_a, qs_a = _seed_subtopic_with_questions(
        db_session, count=1, slug_prefix="A"
    )
    sub_b, qs_b = _seed_subtopic_with_questions(
        db_session, count=1, slug_prefix="B"
    )
    repo = QuizRepository(db=db_session)

    # Alice passes subtopic A.
    a1 = repo.create_attempt(
        user_id=alice.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=sub_a.id,
        started_at=_now(),
        max_score=1,
        seed=1,
    )
    repo.add_attempt_questions(
        a1.id, rows=[{"question_id": qs_a[0].id, "ordinal": 1}]
    )
    repo.submit_attempt(
        a1.id,
        score=1,
        submitted_at=_now(),
        answer_corrections=[
            {"question_id": qs_a[0].id, "is_correct": True}
        ],
    )

    # Alice's pass for A doesn't count for B; doesn't count for Bob.
    assert repo.has_passed_attempt(
        user_id=alice.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=sub_a.id,
    ) is True
    assert repo.has_passed_attempt(
        user_id=alice.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=sub_b.id,
    ) is False
    assert repo.has_passed_attempt(
        user_id=bob.id,
        scope_level=LevelScope.SUBTOPIC,
        scope_id=sub_a.id,
    ) is False
