"""Shared pytest fixtures for the test suite.

The fixtures below are function-scoped per ``testing-standards.md`` so each
test starts against a freshly-created schema. ``Base.metadata`` only contains
``Base`` itself at this point in the build; subsequent tasks add ORM models
that auto-register on ``Base`` simply by importing the model module.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.database.base import Base
from app.infrastructure.database.pragmas import register_pragmas

# Importing each feature's models module registers its tables on
# ``Base.metadata`` so the ``db_session`` fixture's ``create_all`` picks them
# up. The imports are intentionally side-effect only; ``F401`` would otherwise
# flag the unused names.
from app.features.users import models as _users_models  # noqa: F401
from app.features.auth import models as _auth_models  # noqa: F401
from app.features.otp import models as _otp_models  # noqa: F401
from app.features.content import models as _content_models  # noqa: F401
from app.features.progress import models as _progress_models  # noqa: F401
from app.features.xp import models as _xp_models  # noqa: F401
from app.features.quizzes import models as _quiz_models  # noqa: F401
from app.features.mock_exams import models as _mock_exam_models  # noqa: F401
from app.features.achievements import models as _ach_models  # noqa: F401
from app.features.announcements import models as _ann_models  # noqa: F401
from app.features.audit import models as _audit_models  # noqa: F401
from app.features.mastery import models as _mastery_models  # noqa: F401
from app.features.gamification import models as _gamification_models  # noqa: F401
from app.features.tutor import models as _tutor_models  # noqa: F401
from app.features.planner import models as _planner_models  # noqa: F401
from app.features.focus import models as _focus_models  # noqa: F401


@pytest.fixture(scope="session", autouse=True)
def _disable_scheduler() -> Iterator[None]:
    """Keep APScheduler from spinning up timers during tests.

    ``app.infrastructure.scheduler.jobs.start_scheduler`` short-circuits when
    ``DISABLE_SCHEDULER=1`` is set, so the FastAPI lifespan is a no-op for
    background work. We restore the prior value on teardown so a developer
    REPL session left this set explicitly is not silently mutated.
    """
    prior = os.environ.get("DISABLE_SCHEDULER")
    os.environ["DISABLE_SCHEDULER"] = "1"
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("DISABLE_SCHEDULER", None)
        else:
            os.environ["DISABLE_SCHEDULER"] = prior


@pytest.fixture(scope="function")
def db_engine() -> Iterator[Engine]:
    """Fresh in-memory SQLite engine with project pragmas applied.

    ``StaticPool`` keeps every connection bound to the same in-memory database
    so writes from one ``Session`` are visible to a follow-up ``Session``
    within the same test. Without it, each new connection would see an empty
    ``:memory:`` database.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    register_pragmas(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine: Engine) -> Iterator[Session]:
    """Function-scoped ``Session`` against ``db_engine``.

    Creates all tables registered on ``Base.metadata`` at fixture setup and
    drops them on teardown so tests stay isolated.
    """
    Base.metadata.create_all(bind=db_engine)
    SessionTesting = sessionmaker(
        autocommit=False, autoflush=False, bind=db_engine, future=True
    )
    session = SessionTesting()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=db_engine)
