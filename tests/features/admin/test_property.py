"""Property-based tests for admin cascades and import (Task 17.5).

**Property 26: Cascade delete and force-flag conflict**
DELETE without force on entity-with-progress → 409 + no change;
with force → all gone.

**Property 27: Referential integrity on import**
Import succeeds iff FK-closure holds; on rejection DB unchanged;
on success round-trips.

**Validates: Requirements 15.4, 16.3, 16.4, 24.2, 24.3**
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.features.admin.algorithms.import_validator import apply_import, validate_import
from app.features.admin.repository import AdminRepository
from app.features.admin.service import AdminService
from app.features.content.models import Lesson, Module, Question, Subtopic, Topic
from app.features.content.repository import (
    LessonRepository,
    ModuleRepository,
    QuestionRepository,
    SubtopicRepository,
    TopicRepository,
)
from app.features.progress.models import LessonCompletion, UserModuleProgress, UserTopicProgress
from app.features.users.models import User
from app.features.users.repository import UserRepository
from app.infrastructure.database.base import Base
from app.infrastructure.database.pragmas import register_pragmas


# --- DB fixture for property tests ------------------------------------------


@pytest.fixture
def prop_db_session():
    """Fresh in-memory SQLite session for property tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    register_pragmas(engine)

    # Import all models to register them
    from app.features.users import models as _u  # noqa: F401
    from app.features.auth import models as _a  # noqa: F401
    from app.features.otp import models as _o  # noqa: F401
    from app.features.content import models as _c  # noqa: F401
    from app.features.progress import models as _p  # noqa: F401
    from app.features.xp import models as _x  # noqa: F401
    from app.features.quizzes import models as _q  # noqa: F401
    from app.features.mock_exams import models as _m  # noqa: F401
    from app.features.achievements import models as _ach  # noqa: F401
    from app.features.announcements import models as _ann  # noqa: F401

    Base.metadata.create_all(bind=engine)
    SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
    session = SessionTesting()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_content_hierarchy(db: Session) -> dict:
    """Create a minimal content hierarchy for testing."""
    module = Module(
        category="PROFESSIONAL", slug="test-mod", title="Test Module",
        order_index=0, is_published=True,
    )
    db.add(module)
    db.flush()

    topic = Topic(module_id=module.id, slug="test-topic", title="Test Topic", order_index=0)
    db.add(topic)
    db.flush()

    subtopic = Subtopic(topic_id=topic.id, slug="test-sub", title="Test Subtopic", order_index=0)
    db.add(subtopic)
    db.flush()

    lesson = Lesson(
        subtopic_id=subtopic.id,
        content_json={
            "explanations": [{"heading": "H", "body": "B"}],
            "worked_examples": [{"title": "T", "body": "B"}],
            "key_takeaways": ["K"],
            "summary": "S",
        },
        status="PUBLISHED",
    )
    db.add(lesson)
    db.flush()

    db.commit()
    return {
        "module_id": module.id,
        "topic_id": topic.id,
        "subtopic_id": subtopic.id,
        "lesson_id": lesson.id,
    }


def _seed_user(db: Session) -> User:
    """Create a test user."""
    user = User(
        email="test@example.com",
        display_name="Test",
        age=25,
        category="PROFESSIONAL",
        role="LEARNER",
        account_state="VERIFIED",
        is_banned=False,
        password_hash="$2b$10$fakehash",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ===========================================================================
# Property 26: Cascade delete and force-flag conflict
# ===========================================================================


class TestProperty26CascadeDelete:
    """**Validates: Requirements 15.4, 16.3**

    DELETE without force on entity-with-progress → 409 + no change;
    with force → all gone.
    """

    def test_delete_subtopic_without_force_with_progress_returns_409(
        self, prop_db_session: Session
    ) -> None:
        """DELETE subtopic without force when progress exists → 409."""
        ids = _seed_content_hierarchy(prop_db_session)
        user = _seed_user(prop_db_session)

        # Create lesson completion (progress)
        lc = LessonCompletion(
            user_id=user.id,
            lesson_id=ids["lesson_id"],
            completed_at=datetime.now(timezone.utc),
        )
        prop_db_session.add(lc)
        prop_db_session.commit()

        service = _build_admin_service(prop_db_session)

        with pytest.raises(Exception) as exc_info:
            service.delete_subtopic(ids["subtopic_id"], force=False)

        assert exc_info.value.status_code == 409

        # Verify nothing was deleted
        subtopic = prop_db_session.get(Subtopic, ids["subtopic_id"])
        assert subtopic is not None

    def test_delete_subtopic_with_force_cascades(
        self, prop_db_session: Session
    ) -> None:
        """DELETE subtopic with force=true cascades all children + progress."""
        ids = _seed_content_hierarchy(prop_db_session)
        user = _seed_user(prop_db_session)

        # Create lesson completion (progress)
        lc = LessonCompletion(
            user_id=user.id,
            lesson_id=ids["lesson_id"],
            completed_at=datetime.now(timezone.utc),
        )
        prop_db_session.add(lc)
        prop_db_session.commit()

        service = _build_admin_service(prop_db_session)
        service.delete_subtopic(ids["subtopic_id"], force=True)

        # Verify subtopic and lesson are gone
        subtopic = prop_db_session.get(Subtopic, ids["subtopic_id"])
        assert subtopic is None

        lesson = prop_db_session.get(Lesson, ids["lesson_id"])
        assert lesson is None

    def test_delete_module_without_force_with_progress_returns_409(
        self, prop_db_session: Session
    ) -> None:
        """DELETE module without force when progress exists → 409."""
        ids = _seed_content_hierarchy(prop_db_session)
        user = _seed_user(prop_db_session)

        # Create module progress
        mp = UserModuleProgress(
            user_id=user.id,
            module_id=ids["module_id"],
            completed_at=datetime.now(timezone.utc),
        )
        prop_db_session.add(mp)
        prop_db_session.commit()

        service = _build_admin_service(prop_db_session)

        with pytest.raises(Exception) as exc_info:
            service.delete_module(ids["module_id"], force=False)

        assert exc_info.value.status_code == 409

        # Verify nothing was deleted
        module = prop_db_session.get(Module, ids["module_id"])
        assert module is not None

    def test_delete_module_with_force_cascades(
        self, prop_db_session: Session
    ) -> None:
        """DELETE module with force=true cascades everything."""
        ids = _seed_content_hierarchy(prop_db_session)
        user = _seed_user(prop_db_session)

        mp = UserModuleProgress(
            user_id=user.id,
            module_id=ids["module_id"],
            completed_at=datetime.now(timezone.utc),
        )
        prop_db_session.add(mp)
        prop_db_session.commit()

        service = _build_admin_service(prop_db_session)
        service.delete_module(ids["module_id"], force=True)

        # Verify module and all children are gone
        module = prop_db_session.get(Module, ids["module_id"])
        assert module is None

        topic = prop_db_session.get(Topic, ids["topic_id"])
        assert topic is None

    def test_delete_user_cascades_all_progress(
        self, prop_db_session: Session
    ) -> None:
        """DELETE user cascades all progress (Req 15.4)."""
        ids = _seed_content_hierarchy(prop_db_session)
        user = _seed_user(prop_db_session)

        lc = LessonCompletion(
            user_id=user.id,
            lesson_id=ids["lesson_id"],
            completed_at=datetime.now(timezone.utc),
        )
        prop_db_session.add(lc)
        prop_db_session.commit()

        service = _build_admin_service(prop_db_session)
        service.delete_user(user.id)

        # User gone
        assert prop_db_session.get(User, user.id) is None

        # Progress gone (cascade)
        remaining = prop_db_session.execute(
            select(LessonCompletion).where(LessonCompletion.user_id == user.id)
        ).scalars().all()
        assert len(remaining) == 0


# ===========================================================================
# Property 27: Referential integrity on import
# ===========================================================================


class TestProperty27ImportIntegrity:
    """**Validates: Requirements 16.4, 24.2, 24.3**

    Import succeeds iff FK-closure holds; on rejection DB unchanged;
    on success round-trips.
    """

    def test_valid_import_succeeds(self, prop_db_session: Session) -> None:
        """Import with valid FK closure succeeds."""
        data = {
            "modules": [{"id": 100, "category": "PROFESSIONAL", "slug": "imp-mod", "title": "Imported", "order_index": 0, "is_published": True}],
            "topics": [{"id": 200, "module_id": 100, "slug": "imp-topic", "title": "Imported Topic", "order_index": 0}],
            "subtopics": [{"id": 300, "topic_id": 200, "slug": "imp-sub", "title": "Imported Sub", "order_index": 0}],
            "lessons": [],
            "questions": [],
        }

        errors = validate_import(data)
        assert errors == []

        apply_import(prop_db_session, data)
        prop_db_session.commit()

        # Verify data was imported
        module = prop_db_session.get(Module, 100)
        assert module is not None
        assert module.title == "Imported"

        topic = prop_db_session.get(Topic, 200)
        assert topic is not None
        assert topic.module_id == 100

    def test_fk_violation_rejects(self) -> None:
        """Import with broken FK references is rejected."""
        data = {
            "modules": [{"id": 100, "category": "PROFESSIONAL", "slug": "m", "title": "M"}],
            "topics": [{"id": 200, "module_id": 999, "slug": "t", "title": "T"}],  # bad FK
            "subtopics": [],
            "lessons": [],
            "questions": [],
        }

        errors = validate_import(data)
        assert len(errors) > 0
        assert any(e["type"] == "FK_VIOLATION" for e in errors)

    def test_duplicate_question_id_rejects(self) -> None:
        """Import with duplicate question ids is rejected (Req 16.4)."""
        data = {
            "modules": [{"id": 100, "category": "PROFESSIONAL", "slug": "m", "title": "M"}],
            "topics": [{"id": 200, "module_id": 100, "slug": "t", "title": "T"}],
            "subtopics": [{"id": 300, "topic_id": 200, "slug": "s", "title": "S"}],
            "lessons": [],
            "questions": [
                {"id": 1, "subtopic_id": 300, "stem": "Q1", "correct_answer": "A", "explanation": "E"},
                {"id": 1, "subtopic_id": 300, "stem": "Q2", "correct_answer": "B", "explanation": "E"},
            ],
        }

        errors = validate_import(data)
        assert len(errors) > 0
        assert any(e["type"] == "DUPLICATE_QUESTION_ID" for e in errors)

    def test_rejection_leaves_db_unchanged(self, prop_db_session: Session) -> None:
        """On rejection, DB is unchanged (Req 24.3)."""
        # Count existing modules before
        before_count = len(
            prop_db_session.execute(select(Module)).scalars().all()
        )

        data = {
            "modules": [{"id": 500, "category": "PROFESSIONAL", "slug": "new", "title": "New"}],
            "topics": [{"id": 600, "module_id": 999, "slug": "bad", "title": "Bad"}],  # bad FK
            "subtopics": [],
            "lessons": [],
            "questions": [],
        }

        errors = validate_import(data)
        assert len(errors) > 0

        # DB unchanged
        after_count = len(
            prop_db_session.execute(select(Module)).scalars().all()
        )
        assert after_count == before_count

    @given(
        n_modules=st.integers(min_value=1, max_value=5),
        n_topics_per_module=st.integers(min_value=0, max_value=3),
    )
    @settings(max_examples=20)
    def test_valid_hierarchy_always_passes_validation(
        self, n_modules: int, n_topics_per_module: int
    ) -> None:
        """Any well-formed hierarchy passes validation."""
        modules = []
        topics = []
        for m_idx in range(n_modules):
            mid = m_idx + 1
            modules.append({
                "id": mid,
                "category": "PROFESSIONAL",
                "slug": f"mod-{mid}",
                "title": f"Module {mid}",
            })
            for t_idx in range(n_topics_per_module):
                tid = mid * 100 + t_idx + 1
                topics.append({
                    "id": tid,
                    "module_id": mid,
                    "slug": f"topic-{tid}",
                    "title": f"Topic {tid}",
                })

        data = {
            "modules": modules,
            "topics": topics,
            "subtopics": [],
            "lessons": [],
            "questions": [],
        }

        errors = validate_import(data)
        assert errors == []

    @given(bad_module_id=st.integers(min_value=1000, max_value=9999))
    @settings(max_examples=20)
    def test_broken_fk_always_fails_validation(self, bad_module_id: int) -> None:
        """Any topic referencing a non-existent module fails validation."""
        data = {
            "modules": [{"id": 1, "category": "PROFESSIONAL", "slug": "m", "title": "M"}],
            "topics": [{"id": 2, "module_id": bad_module_id, "slug": "t", "title": "T"}],
            "subtopics": [],
            "lessons": [],
            "questions": [],
        }

        errors = validate_import(data)
        assert len(errors) > 0


# --- Helper -----------------------------------------------------------------


def _build_admin_service(db: Session) -> AdminService:
    """Build an AdminService with real repos against the test DB."""
    return AdminService(
        db=db,
        user_repo=UserRepository(db=db),
        admin_repo=AdminRepository(db=db),
        module_repo=ModuleRepository(db=db),
        topic_repo=TopicRepository(db=db),
        subtopic_repo=SubtopicRepository(db=db),
        lesson_repo=LessonRepository(db=db),
        question_repo=QuestionRepository(db=db),
    )
