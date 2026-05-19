"""Repository tests for the mock-exam slice (Task 12.1).

Exercises :class:`MockExamRepository` against in-memory SQLite — no
mocks, per ``testing-standards.md``. Each test seeds the parent rows
(User -> Module -> Topic -> Subtopic -> Question and the Mock-exam
config) so foreign-key constraints are honoured and the partial
unique index is exercised against real schema.
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
from app.features.mock_exams.models import (
    MockExamAttemptStatus,
    MockExamNavPolicy,
    MockExamSubmissionMode,
)
from app.features.mock_exams.repository import MockExamRepository
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


def _seed_module_with_questions(
    db: Session, *, count: int = 3, slug_prefix: str = "m"
) -> tuple[Module, list[Question]]:
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
            level_scope=LevelScope.MODULE.value,
            stem=f"Q{i}-{slug_prefix}?",
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
    return module, questions


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# --- config CRUD -----------------------------------------------------------


def test_upsert_config_inserts_and_returns_row(db_session: Session) -> None:
    repo = MockExamRepository(db=db_session)

    cfg = repo.upsert_config(
        category=Category.PROFESSIONAL,
        total_questions=50,
        weights_json={"1": 25, "2": 25},
        time_limit_minutes=180,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        pass_threshold=0.80,
    )

    assert cfg.category == Category.PROFESSIONAL.value
    assert cfg.total_questions == 50
    assert cfg.weights_json == {"1": 25, "2": 25}
    assert cfg.time_limit_minutes == 180
    assert cfg.nav_policy == MockExamNavPolicy.LINEAR_NO_REVISIT.value
    assert cfg.pass_threshold == 0.80


def test_upsert_config_updates_existing_row(db_session: Session) -> None:
    repo = MockExamRepository(db=db_session)
    repo.upsert_config(
        category=Category.PROFESSIONAL,
        total_questions=50,
        weights_json={"1": 50},
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
    )

    updated = repo.upsert_config(
        category=Category.PROFESSIONAL,
        total_questions=100,
        weights_json={"1": 50, "2": 50},
        time_limit_minutes=240,
        nav_policy=MockExamNavPolicy.FREE_NAV,
        pass_threshold=0.75,
    )

    assert updated.total_questions == 100
    assert updated.weights_json == {"1": 50, "2": 50}
    assert updated.nav_policy == MockExamNavPolicy.FREE_NAV.value
    assert updated.pass_threshold == 0.75


def test_get_config_returns_none_when_absent(db_session: Session) -> None:
    repo = MockExamRepository(db=db_session)
    assert repo.get_config(Category.PROFESSIONAL) is None


# --- create_attempt --------------------------------------------------------


def test_create_attempt_persists_all_fields(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = MockExamRepository(db=db_session)
    when = _now()

    attempt = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=when,
        max_score=50,
        seed=987654321,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )

    assert attempt.id is not None
    assert attempt.user_id == user.id
    assert attempt.category == Category.PROFESSIONAL.value
    assert attempt.status == MockExamAttemptStatus.IN_PROGRESS.value
    assert attempt.max_score == 50
    assert attempt.seed == 987654321
    assert attempt.focus_loss_events == []
    assert attempt.nav_policy == MockExamNavPolicy.LINEAR_NO_REVISIT.value
    assert attempt.time_limit_minutes == 180
    assert attempt.score is None
    assert attempt.submitted_at is None
    assert attempt.submission_mode is None


def test_partial_unique_index_prevents_two_in_progress(
    db_session: Session,
) -> None:
    """Property 36 / Req 10.8 — at-most-one IN_PROGRESS per user."""
    user = _make_user(db_session)
    repo = MockExamRepository(db=db_session)

    repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=50,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )
    with pytest.raises(IntegrityError):
        repo.create_attempt(
            user_id=user.id,
            category=Category.PROFESSIONAL,
            started_at=_now(),
            max_score=50,
            seed=2,
            nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
            time_limit_minutes=180,
        )
    db_session.rollback()


def test_partial_unique_index_allows_in_progress_after_submit(
    db_session: Session,
) -> None:
    """Once the prior attempt is SUBMITTED, a new IN_PROGRESS is fine."""
    user = _make_user(db_session)
    _, questions = _seed_module_with_questions(db_session)
    repo = MockExamRepository(db=db_session)

    a = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=1,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
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
        submission_mode=MockExamSubmissionMode.MANUAL,
        answer_corrections=[
            {"question_id": questions[0].id, "is_correct": True}
        ],
    )

    # Fresh attempt is now allowed.
    b = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=1,
        seed=2,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )
    assert b.id != a.id


def test_partial_unique_index_isolates_per_user(db_session: Session) -> None:
    alice = _make_user(db_session)
    bob = _make_user(db_session, email="bob@example.com")
    repo = MockExamRepository(db=db_session)

    repo.create_attempt(
        user_id=alice.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=50,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )
    bob_attempt = repo.create_attempt(
        user_id=bob.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=50,
        seed=2,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )
    assert bob_attempt.user_id == bob.id


# --- get_attempt / get_attempt_for_user / get_in_progress_for_user ---------


def test_get_attempt_for_user_authorizes_owner(db_session: Session) -> None:
    alice = _make_user(db_session)
    bob = _make_user(db_session, email="bob@example.com")
    repo = MockExamRepository(db=db_session)
    a = repo.create_attempt(
        user_id=alice.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=50,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )

    assert repo.get_attempt_for_user(a.id, alice.id) is not None
    assert repo.get_attempt_for_user(a.id, bob.id) is None
    assert repo.get_attempt_for_user(99999, alice.id) is None


def test_get_in_progress_for_user_returns_only_in_progress(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    _, questions = _seed_module_with_questions(db_session)
    repo = MockExamRepository(db=db_session)

    # No attempt yet.
    assert repo.get_in_progress_for_user(user.id) is None

    # Create + submit one — get_in_progress should now be None.
    a = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=1,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )
    repo.add_attempt_questions(
        a.id,
        rows=[{"question_id": questions[0].id, "ordinal": 1}],
    )
    repo.submit_attempt(
        a.id,
        score=0,
        submitted_at=_now(),
        submission_mode=MockExamSubmissionMode.MANUAL,
        answer_corrections=[
            {"question_id": questions[0].id, "is_correct": False}
        ],
    )
    assert repo.get_in_progress_for_user(user.id) is None

    # Start a new one — now visible.
    b = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=50,
        seed=2,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )
    found = repo.get_in_progress_for_user(user.id)
    assert found is not None
    assert found.id == b.id


# --- add_attempt_questions / list_attempt_answers / set_answer -------------


def test_add_attempt_questions_inserts_all_rows(db_session: Session) -> None:
    user = _make_user(db_session)
    _, questions = _seed_module_with_questions(db_session, count=3)
    repo = MockExamRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=3,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
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
    for r in listed:
        assert r.selected_answer is None
        assert r.is_correct is None
        assert r.finalized_at is None
        assert r.displayed_options == ["A", "B", "C", "D"]


def test_set_answer_updates_selection(db_session: Session) -> None:
    user = _make_user(db_session)
    _, questions = _seed_module_with_questions(db_session, count=1)
    repo = MockExamRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=1,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )
    repo.add_attempt_questions(
        a.id, rows=[{"question_id": questions[0].id, "ordinal": 1}]
    )

    when = _now()
    row = repo.set_answer(
        attempt_id=a.id,
        question_id=questions[0].id,
        selected_answer="A",
        answered_at=when,
    )

    assert row.selected_answer == "A"
    assert row.is_correct is None
    assert row.answered_at is not None
    assert row.finalized_at is None


def test_set_answer_with_finalized_at_stamps_lock(db_session: Session) -> None:
    user = _make_user(db_session)
    _, questions = _seed_module_with_questions(db_session, count=1)
    repo = MockExamRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=1,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )
    repo.add_attempt_questions(
        a.id, rows=[{"question_id": questions[0].id, "ordinal": 1}]
    )
    when = _now()

    row = repo.set_answer(
        attempt_id=a.id,
        question_id=questions[0].id,
        selected_answer="A",
        answered_at=when,
        finalized_at=when,
    )
    assert row.finalized_at is not None


def test_set_answer_does_not_re_finalize_already_locked(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    _, questions = _seed_module_with_questions(db_session, count=1)
    repo = MockExamRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=1,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )
    repo.add_attempt_questions(
        a.id, rows=[{"question_id": questions[0].id, "ordinal": 1}]
    )

    first = _now()
    repo.set_answer(
        attempt_id=a.id,
        question_id=questions[0].id,
        selected_answer="A",
        answered_at=first,
        finalized_at=first,
    )
    second = _now()
    row = repo.set_answer(
        attempt_id=a.id,
        question_id=questions[0].id,
        selected_answer="B",
        answered_at=second,
        finalized_at=second,
    )
    # The original lock timestamp survives; the row is still finalized.
    assert row.finalized_at is not None


def test_set_answer_raises_for_unknown_pair(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = MockExamRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=1,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )

    with pytest.raises(LookupError):
        repo.set_answer(
            attempt_id=a.id,
            question_id=99999,
            selected_answer="A",
            answered_at=_now(),
        )


def test_mark_finalized_sets_lock(db_session: Session) -> None:
    user = _make_user(db_session)
    _, questions = _seed_module_with_questions(db_session, count=1)
    repo = MockExamRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=1,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )
    repo.add_attempt_questions(
        a.id, rows=[{"question_id": questions[0].id, "ordinal": 1}]
    )

    row = repo.mark_finalized(attempt_id=a.id, ordinal=1, finalized_at=_now())

    assert row is not None
    assert row.finalized_at is not None


# --- submit_attempt --------------------------------------------------------


def test_submit_attempt_manual_persists_all_fields(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    _, questions = _seed_module_with_questions(db_session, count=2)
    repo = MockExamRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=2,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
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
        submission_mode=MockExamSubmissionMode.MANUAL,
        answer_corrections=[
            {"question_id": questions[0].id, "is_correct": True},
            {"question_id": questions[1].id, "is_correct": False},
        ],
    )

    assert submitted.status == MockExamAttemptStatus.SUBMITTED.value
    assert submitted.submission_mode == MockExamSubmissionMode.MANUAL.value
    assert submitted.score == 1
    assert submitted.submitted_at is not None

    rows = repo.list_attempt_answers(a.id)
    by_qid = {r.question_id: r for r in rows}
    assert by_qid[questions[0].id].is_correct is True
    assert by_qid[questions[1].id].is_correct is False


def test_submit_attempt_auto_submit_uses_auto_status(
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    _, questions = _seed_module_with_questions(db_session, count=1)
    repo = MockExamRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=1,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )
    repo.add_attempt_questions(
        a.id, rows=[{"question_id": questions[0].id, "ordinal": 1}]
    )

    submitted = repo.submit_attempt(
        a.id,
        score=0,
        submitted_at=_now(),
        submission_mode=MockExamSubmissionMode.AUTO_SUBMIT,
        answer_corrections=[
            {"question_id": questions[0].id, "is_correct": False}
        ],
    )

    assert submitted.status == MockExamAttemptStatus.AUTO_SUBMITTED.value
    assert submitted.submission_mode == MockExamSubmissionMode.AUTO_SUBMIT.value


def test_submit_attempt_raises_for_missing_attempt(
    db_session: Session,
) -> None:
    repo = MockExamRepository(db=db_session)
    with pytest.raises(LookupError):
        repo.submit_attempt(
            99999,
            score=0,
            submitted_at=_now(),
            submission_mode=MockExamSubmissionMode.MANUAL,
            answer_corrections=[],
        )


# --- focus-loss events -----------------------------------------------------


def test_append_focus_loss_appends_entry(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = MockExamRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=50,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )

    when_a = datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
    when_b = datetime(2025, 1, 1, 0, 0, 2, tzinfo=timezone.utc)
    repo.append_focus_loss(a.id, kind="blur", at=when_a)
    repo.append_focus_loss(a.id, kind="tab_switch", at=when_b)

    refreshed = repo.get_attempt(a.id)
    assert refreshed is not None
    assert len(refreshed.focus_loss_events) == 2
    assert refreshed.focus_loss_events[0]["kind"] == "blur"
    assert refreshed.focus_loss_events[1]["kind"] == "tab_switch"


def test_update_focus_loss_alias_matches_append(db_session: Session) -> None:
    user = _make_user(db_session)
    repo = MockExamRepository(db=db_session)
    a = repo.create_attempt(
        user_id=user.id,
        category=Category.PROFESSIONAL,
        started_at=_now(),
        max_score=50,
        seed=1,
        nav_policy=MockExamNavPolicy.LINEAR_NO_REVISIT,
        time_limit_minutes=180,
    )

    repo.update_focus_loss(a.id, kind="blur", at=_now())

    refreshed = repo.get_attempt(a.id)
    assert refreshed is not None
    assert len(refreshed.focus_loss_events) == 1
