"""Seed loader for development/testing.

Creates minimal fixtures sufficient to make the system runnable end-to-end:
- 1 PROFESSIONAL module + 1 SUB_PROFESSIONAL module
- Each with 2 topics x 2 subtopics x 1 lesson
- Each subtopic with 25 quality-gated questions (enough for a 20-question quiz)
- One admin user (email: admin@cse.local, password: Admin1Pass!)
- One learner user per category (email: learner-pro@cse.local, learner-sub@cse.local)
- Achievement seed rows (MVP + Phase 2)
- Mock-exam-config rows for both categories at total_questions=50 for MVP

Usage:
    python -m scripts.seed
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.features.achievements.repository import AchievementRepository
from app.features.achievements.seed import seed_all_achievements
from app.features.content.models import (
    Difficulty,
    Lesson,
    LessonStatus,
    LevelScope,
    Module,
    Question,
    QuestionType,
    Subtopic,
    Topic,
)
from app.features.mock_exams.models import MockExamConfig, MockExamNavPolicy
from app.features.users.models import AccountState, Category, Role, User
from app.infrastructure.database.base import Base
from app.infrastructure.security.passwords import hash_password


def _make_lesson_content() -> dict[str, Any]:
    """Return a minimal valid LessonContent JSON blob."""
    return {
        "explanations": [
            {"title": "Core Concept", "body": "This is the core concept explanation."}
        ],
        "worked_examples": [
            {"title": "Example 1", "problem": "Solve X", "solution": "X = 42"}
        ],
        "key_takeaways": ["Key point 1", "Key point 2"],
        "summary": "This lesson covers the fundamental concepts.",
    }


def _make_questions(
    subtopic_id: int,
    topic_id: int,
    module_id: int,
    category: str,
    count: int = 25,
) -> list[Question]:
    """Generate ``count`` quality-gated MC questions for a subtopic."""
    difficulties = [Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD]
    questions: list[Question] = []
    for i in range(count):
        diff = difficulties[i % 3]
        correct = f"Option {(i % 4) + 1}"
        options = [f"Option {j}" for j in range(1, 5)]
        questions.append(
            Question(
                subtopic_id=subtopic_id,
                topic_id=topic_id,
                module_id=module_id,
                category=category,
                level_scope=LevelScope.SUBTOPIC.value,
                stem=f"Question {i + 1} for subtopic {subtopic_id}: What is the answer?",
                options=json.loads(json.dumps(options)),
                correct_answer=correct,
                explanation=f"The correct answer is {correct} because of reason {i + 1}.",
                difficulty=diff.value,
                qtype=QuestionType.MULTIPLE_CHOICE.value,
                is_active=True,
            )
        )
    return questions


def seed_database(session: Session) -> dict[str, Any]:
    """Seed the database with minimal fixtures. Returns a summary dict.

    Idempotent: checks if admin user exists before creating anything.
    """
    # Check idempotency — if admin already exists, skip
    existing_admin = session.query(User).filter(User.email == "admin@cse.local").first()
    if existing_admin is not None:
        return {"status": "already_seeded", "admin_id": existing_admin.id}

    # --- Users ---
    admin_hash = hash_password("Admin1Pass!")
    admin = User(
        email="admin@cse.local",
        display_name="Admin User",
        age=30,
        category=Category.PROFESSIONAL.value,
        role=Role.ADMIN.value,
        account_state=AccountState.VERIFIED.value,
        is_banned=False,
        tz_name="Asia/Manila",
        password_hash=admin_hash,
    )
    session.add(admin)

    learner_pro_hash = hash_password("Learner1Pass!")
    learner_pro = User(
        email="learner-pro@cse.local",
        display_name="Pro Learner",
        age=25,
        category=Category.PROFESSIONAL.value,
        role=Role.LEARNER.value,
        account_state=AccountState.VERIFIED.value,
        is_banned=False,
        tz_name="Asia/Manila",
        password_hash=learner_pro_hash,
    )
    session.add(learner_pro)

    learner_sub_hash = hash_password("Learner1Pass!")
    learner_sub = User(
        email="learner-sub@cse.local",
        display_name="Sub-Pro Learner",
        age=22,
        category=Category.SUB_PROFESSIONAL.value,
        role=Role.LEARNER.value,
        account_state=AccountState.VERIFIED.value,
        is_banned=False,
        tz_name="Asia/Manila",
        password_hash=learner_sub_hash,
    )
    session.add(learner_sub)
    session.flush()

    # --- Content hierarchy ---
    # PROFESSIONAL category: 1 module, 2 topics, 2 subtopics each
    pro_module = Module(
        category=Category.PROFESSIONAL.value,
        slug="pro-module-1",
        title="Professional Module 1",
        order_index=1,
        is_published=True,
    )
    session.add(pro_module)
    session.flush()

    # SUB_PROFESSIONAL category: 1 module, 2 topics, 2 subtopics each
    sub_module = Module(
        category=Category.SUB_PROFESSIONAL.value,
        slug="sub-module-1",
        title="Sub-Professional Module 1",
        order_index=1,
        is_published=True,
    )
    session.add(sub_module)
    session.flush()

    modules_data = [
        (pro_module, Category.PROFESSIONAL.value),
        (sub_module, Category.SUB_PROFESSIONAL.value),
    ]

    all_subtopic_ids: list[int] = []
    lesson_content = _make_lesson_content()

    for module, cat in modules_data:
        for t_idx in range(1, 3):
            topic = Topic(
                module_id=module.id,
                slug=f"{module.slug}-topic-{t_idx}",
                title=f"{module.title} Topic {t_idx}",
                order_index=t_idx,
            )
            session.add(topic)
            session.flush()

            for s_idx in range(1, 3):
                subtopic = Subtopic(
                    topic_id=topic.id,
                    slug=f"{topic.slug}-subtopic-{s_idx}",
                    title=f"{topic.title} Subtopic {s_idx}",
                    order_index=s_idx,
                )
                session.add(subtopic)
                session.flush()
                all_subtopic_ids.append(subtopic.id)

                # Lesson for this subtopic
                lesson = Lesson(
                    subtopic_id=subtopic.id,
                    content_json=lesson_content,
                    status=LessonStatus.PUBLISHED.value,
                )
                session.add(lesson)

                # 25 questions per subtopic
                questions = _make_questions(
                    subtopic_id=subtopic.id,
                    topic_id=topic.id,
                    module_id=module.id,
                    category=cat,
                    count=25,
                )
                for q in questions:
                    session.add(q)

    session.flush()

    # --- Mock exam configs ---
    # PROFESSIONAL: total_questions=50, weights split across 1 module (all 50)
    pro_config = MockExamConfig(
        category=Category.PROFESSIONAL.value,
        total_questions=50,
        weights_json={str(pro_module.id): 50},
        time_limit_minutes=180,
        nav_policy=MockExamNavPolicy.FREE_NAV.value,
        pass_threshold=0.80,
    )
    session.add(pro_config)

    sub_config = MockExamConfig(
        category=Category.SUB_PROFESSIONAL.value,
        total_questions=50,
        weights_json={str(sub_module.id): 50},
        time_limit_minutes=180,
        nav_policy=MockExamNavPolicy.FREE_NAV.value,
        pass_threshold=0.80,
    )
    session.add(sub_config)

    # --- Achievements ---
    ach_repo = AchievementRepository(db=session)
    seed_all_achievements(ach_repo)

    session.commit()

    return {
        "status": "seeded",
        "admin_id": admin.id,
        "learner_pro_id": learner_pro.id,
        "learner_sub_id": learner_sub.id,
        "pro_module_id": pro_module.id,
        "sub_module_id": sub_module.id,
        "subtopic_ids": all_subtopic_ids,
    }


def run_standalone() -> None:
    """Run the seed against the production database (file-backed SQLite)."""
    from app.infrastructure.database.session import SessionLocal, engine

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        result = seed_database(session)
        print(f"Seed result: {result}")
    finally:
        session.close()


if __name__ == "__main__":
    run_standalone()
