"""Export algorithm: produce a JSON artifact of all application data.

Excludes password_hash, OTP rows, and sessions per Req 17.3 / 24.1.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.achievements.models import Achievement, UserAchievement
from app.features.content.models import (
    Lesson,
    Module,
    Question,
    Subtopic,
    Topic,
)
from app.features.mock_exams.models import (
    MockExamAttempt,
    MockExamAttemptAnswer,
    MockExamConfig,
)
from app.features.progress.models import (
    LessonCompletion,
    UserModuleProgress,
    UserTopicProgress,
)
from app.features.quizzes.models import QuizAttempt, QuizAttemptAnswer
from app.features.users.models import User
from app.features.xp.models import UserXP, XPEvent


def _serialize_row(row: Any, exclude_fields: set[str] | None = None) -> dict[str, Any]:
    """Convert an ORM row to a dict, excluding specified fields."""
    exclude = exclude_fields or set()
    result = {}
    for col in row.__table__.columns:
        if col.name in exclude:
            continue
        val = getattr(row, col.name)
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        result[col.name] = val
    return result


def build_export(db: Session) -> dict[str, Any]:
    """Build the full export artifact (Req 17.3, 24.1).

    Excludes: password_hash from users, all OTP rows, all session rows.
    """
    # Users (exclude password_hash)
    users = [
        _serialize_row(u, exclude_fields={"password_hash"})
        for u in db.execute(select(User)).scalars().all()
    ]

    # Content hierarchy
    modules = [_serialize_row(m) for m in db.execute(select(Module)).scalars().all()]
    topics = [_serialize_row(t) for t in db.execute(select(Topic)).scalars().all()]
    subtopics = [_serialize_row(s) for s in db.execute(select(Subtopic)).scalars().all()]
    lessons = [_serialize_row(l) for l in db.execute(select(Lesson)).scalars().all()]
    questions = [_serialize_row(q) for q in db.execute(select(Question)).scalars().all()]

    # Mock exam configs
    configs = [_serialize_row(c) for c in db.execute(select(MockExamConfig)).scalars().all()]

    # Progress
    lesson_completions = [
        _serialize_row(lc) for lc in db.execute(select(LessonCompletion)).scalars().all()
    ]
    topic_progress = [
        _serialize_row(tp) for tp in db.execute(select(UserTopicProgress)).scalars().all()
    ]
    module_progress = [
        _serialize_row(mp) for mp in db.execute(select(UserModuleProgress)).scalars().all()
    ]

    # Quiz attempts
    quiz_attempts = [
        _serialize_row(qa) for qa in db.execute(select(QuizAttempt)).scalars().all()
    ]
    quiz_answers = [
        _serialize_row(qa) for qa in db.execute(select(QuizAttemptAnswer)).scalars().all()
    ]

    # Mock exam attempts
    mock_attempts = [
        _serialize_row(ma) for ma in db.execute(select(MockExamAttempt)).scalars().all()
    ]
    mock_answers = [
        _serialize_row(ma) for ma in db.execute(select(MockExamAttemptAnswer)).scalars().all()
    ]

    # XP
    user_xp = [_serialize_row(ux) for ux in db.execute(select(UserXP)).scalars().all()]
    xp_events = [_serialize_row(xe) for xe in db.execute(select(XPEvent)).scalars().all()]

    # Achievements
    achievements = [
        _serialize_row(a) for a in db.execute(select(Achievement)).scalars().all()
    ]
    user_achievements = [
        _serialize_row(ua) for ua in db.execute(select(UserAchievement)).scalars().all()
    ]

    return {
        "users": users,
        "modules": modules,
        "topics": topics,
        "subtopics": subtopics,
        "lessons": lessons,
        "questions": questions,
        "mock_exam_configs": configs,
        "lesson_completions": lesson_completions,
        "user_topic_progress": topic_progress,
        "user_module_progress": module_progress,
        "quiz_attempts": quiz_attempts,
        "quiz_attempt_answers": quiz_answers,
        "mock_exam_attempts": mock_attempts,
        "mock_exam_attempt_answers": mock_answers,
        "user_xp": user_xp,
        "xp_events": xp_events,
        "achievements": achievements,
        "user_achievements": user_achievements,
    }
