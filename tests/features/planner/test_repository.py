"""Repository tests for the planner feature — real DB, no mocks."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.features.content.models import Module, Subtopic, Topic
from app.features.planner.models import StudyPlan, StudyPlanDay
from app.features.planner.repository import StudyPlanDayRepository, StudyPlanRepository
from app.features.users.models import User


def _seed_user(db: Session) -> User:
    user = User(
        email="planner@test.com",
        display_name="Planner Tester",
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


def _seed_subtopic(db: Session) -> int:
    mod = Module(category="PROFESSIONAL", slug="mod-p", title="Mod", order_index=0)
    db.add(mod)
    db.commit()
    db.refresh(mod)
    topic = Topic(module_id=mod.id, slug="top-p", title="Top", order_index=0)
    db.add(topic)
    db.commit()
    db.refresh(topic)
    sub = Subtopic(topic_id=topic.id, slug="sub-p", title="Sub", order_index=0)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub.id


def test_create_and_get_active_plan(db_session: Session) -> None:
    user = _seed_user(db_session)
    repo = StudyPlanRepository(db=db_session)

    plan = StudyPlan(
        user_id=user.id,
        target_exam_date=date.today() + timedelta(days=30),
        available_hours_per_day=2.0,
        target_score=0.85,
        status="ACTIVE",
    )
    plan = repo.create(plan)

    active = repo.get_active_plan(user.id)
    assert active is not None
    assert active.id == plan.id
    assert active.status == "ACTIVE"


def test_abandon_plan(db_session: Session) -> None:
    user = _seed_user(db_session)
    repo = StudyPlanRepository(db=db_session)

    plan = StudyPlan(
        user_id=user.id,
        target_exam_date=date.today() + timedelta(days=30),
        available_hours_per_day=2.0,
        target_score=0.85,
        status="ACTIVE",
    )
    plan = repo.create(plan)
    repo.abandon_plan(plan)

    active = repo.get_active_plan(user.id)
    assert active is None


def test_get_today_tasks(db_session: Session) -> None:
    user = _seed_user(db_session)
    subtopic_id = _seed_subtopic(db_session)
    plan_repo = StudyPlanRepository(db=db_session)
    day_repo = StudyPlanDayRepository(db=db_session)

    plan = StudyPlan(
        user_id=user.id,
        target_exam_date=date.today() + timedelta(days=30),
        available_hours_per_day=2.0,
        target_score=0.85,
        status="ACTIVE",
    )
    plan = plan_repo.create(plan)

    today = date.today()
    day = StudyPlanDay(
        plan_id=plan.id,
        plan_date=today,
        subtopic_id=subtopic_id,
        activity_type="lesson",
        estimated_minutes=30,
    )
    day_repo.create(day)

    tasks = day_repo.get_today_tasks(plan.id, today)
    assert len(tasks) == 1
    assert tasks[0].activity_type == "lesson"


def test_mark_complete(db_session: Session) -> None:
    user = _seed_user(db_session)
    subtopic_id = _seed_subtopic(db_session)
    plan_repo = StudyPlanRepository(db=db_session)
    day_repo = StudyPlanDayRepository(db=db_session)

    plan = StudyPlan(
        user_id=user.id,
        target_exam_date=date.today() + timedelta(days=30),
        available_hours_per_day=2.0,
        target_score=0.85,
        status="ACTIVE",
    )
    plan = plan_repo.create(plan)

    day = StudyPlanDay(
        plan_id=plan.id,
        plan_date=date.today(),
        subtopic_id=subtopic_id,
        activity_type="quiz",
        estimated_minutes=20,
    )
    day = day_repo.create(day)

    day_repo.mark_complete(day)
    assert day.completed is True
    assert day.completed_at is not None
