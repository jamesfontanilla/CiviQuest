"""Repository tests for the tutor feature — real DB, no mocks."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.tutor.models import TutorInteraction
from app.features.tutor.repository import TutorRepository
from app.features.users.models import User
from app.features.content.models import Module, Topic, Subtopic, Question


def _seed_user(db: Session) -> User:
    user = User(
        email="tutor@test.com",
        display_name="Tutor Tester",
        age=25,
        category="PROFESSIONAL",
        role="LEARNER",
        account_state="VERIFIED",
        password_hash="$2b$10$fakehash",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _seed_question(db: Session) -> Question:
    mod = Module(category="PROFESSIONAL", slug="mod-t", title="Mod", order_index=0)
    db.add(mod)
    db.commit()
    db.refresh(mod)

    topic = Topic(module_id=mod.id, slug="top-t", title="Top", order_index=0)
    db.add(topic)
    db.commit()
    db.refresh(topic)

    sub = Subtopic(topic_id=topic.id, slug="sub-t", title="Sub", order_index=0)
    db.add(sub)
    db.commit()
    db.refresh(sub)

    q = Question(
        subtopic_id=sub.id,
        topic_id=topic.id,
        module_id=mod.id,
        category="PROFESSIONAL",
        level_scope="SUBTOPIC",
        stem="What is 2+2?",
        options=["3", "4", "5", "6"],
        correct_answer="4",
        explanation="2+2 equals 4.",
        difficulty="EASY",
        qtype="MULTIPLE_CHOICE",
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


def test_create_interaction(db_session: Session) -> None:
    user = _seed_user(db_session)
    q = _seed_question(db_session)
    repo = TutorRepository(db=db_session)

    interaction = repo.create_interaction(
        user_id=user.id,
        question_id=q.id,
        subtopic_id=q.subtopic_id,
        interaction_type="explain_answer",
        request_context={"selected_answer": "3"},
        response_text="The answer is 4.",
    )

    assert interaction.id is not None
    assert interaction.user_id == user.id
    assert interaction.question_id == q.id
    assert interaction.interaction_type == "explain_answer"
    assert interaction.response_text == "The answer is 4."
    assert interaction.helpful is None


def test_rate_interaction(db_session: Session) -> None:
    user = _seed_user(db_session)
    q = _seed_question(db_session)
    repo = TutorRepository(db=db_session)

    interaction = repo.create_interaction(
        user_id=user.id,
        question_id=q.id,
        subtopic_id=q.subtopic_id,
        interaction_type="hint",
        request_context=None,
        response_text="Here's a hint.",
    )

    result = repo.rate_interaction(interaction.id, True)
    assert result is not None
    assert result.helpful is True


def test_rate_nonexistent_interaction(db_session: Session) -> None:
    repo = TutorRepository(db=db_session)
    result = repo.rate_interaction(9999, True)
    assert result is None
