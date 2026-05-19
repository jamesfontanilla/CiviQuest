"""Repository tests for the content slice against in-memory SQLite.

Per ``testing-standards.md`` the repository layer is exercised against a
real DB engine — no mocks. The tests cover:

- ``ModuleRepository.list_by_category``  (Req 5.1, 5.2)
- ``TopicRepository.list_by_module``     (ordering)
- ``SubtopicRepository.list_by_topic``   (ordering)
- ``LessonRepository.get_by_subtopic_id`` (one-per-subtopic lookup)
- ``QuestionRepository.list_active_passing_quality_gate`` — every Req 18.x
  failure path is asserted, plus scope filters and inactive exclusion.
- ``QuestionRepository.log_rejection`` (Req 18.4)
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.features.content.algorithms.quality_gate import (
    RULE_MC_OPTION_COUNT,
)
from app.features.content.models import (
    LessonStatus,
    LevelScope,
    Lesson,
    Module,
    Question,
    Subtopic,
    Topic,
)
from app.features.content.repository import (
    LessonRepository,
    ModuleRepository,
    QuestionRepository,
    SubtopicRepository,
    TopicRepository,
)
from app.features.users.models import Category


# ----- Fixtures / factories -------------------------------------------------


def _make_module(
    db: Session,
    *,
    category: Category = Category.PROFESSIONAL,
    slug: str = "math",
    title: str = "Math",
    order_index: int = 0,
    is_published: bool = True,
) -> Module:
    m = Module(
        category=category.value,
        slug=slug,
        title=title,
        order_index=order_index,
        is_published=is_published,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _make_topic(
    db: Session, module_id: int, *, slug: str = "algebra", order_index: int = 0
) -> Topic:
    t = Topic(
        module_id=module_id,
        slug=slug,
        title=slug.title(),
        order_index=order_index,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_subtopic(
    db: Session,
    topic_id: int,
    *,
    slug: str = "linear-equations",
    order_index: int = 0,
) -> Subtopic:
    s = Subtopic(
        topic_id=topic_id,
        slug=slug,
        title=slug.replace("-", " ").title(),
        order_index=order_index,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _make_lesson(
    db: Session,
    subtopic_id: int,
    *,
    status: LessonStatus = LessonStatus.PUBLISHED,
) -> Lesson:
    lesson = Lesson(
        subtopic_id=subtopic_id,
        content_json={
            "explanations": [{"heading": "I", "body": "b"}],
            "worked_examples": [{"title": "T", "body": "b"}],
            "key_takeaways": ["k"],
            "summary": "s",
        },
        status=status.value,
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return lesson


def _make_question(
    db: Session,
    *,
    subtopic_id: int = 1,
    topic_id: int = 1,
    module_id: int = 1,
    category: Category = Category.PROFESSIONAL,
    level_scope: LevelScope = LevelScope.SUBTOPIC,
    stem: str = "What is 2 + 2?",
    options: list | None = None,
    correct_answer: str = "4",
    explanation: str = "Addition.",
    difficulty: str = "EASY",
    qtype: str = "MULTIPLE_CHOICE",
    is_active: bool = True,
) -> Question:
    """Insert a question directly. Defaults to a valid MC question.

    Tests override individual fields to manufacture each Req 18.x violation;
    we deliberately bypass ``QuestionCreate`` here so a mis-shaped row makes
    it into the DB and the quality gate has something to filter out.
    """
    if options is None and qtype == "MULTIPLE_CHOICE":
        options = ["3", "4", "5", "6"]
    q = Question(
        subtopic_id=subtopic_id,
        topic_id=topic_id,
        module_id=module_id,
        category=category.value,
        level_scope=level_scope.value,
        stem=stem,
        options=options,
        correct_answer=correct_answer,
        explanation=explanation,
        difficulty=difficulty,
        qtype=qtype,
        is_active=is_active,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


def _seed_hierarchy(
    db: Session, *, category: Category = Category.PROFESSIONAL
) -> tuple[Module, Topic, Subtopic]:
    """Create one module/topic/subtopic chain and return all three rows."""
    m = _make_module(db, category=category, slug=f"mod-{category.value.lower()}")
    t = _make_topic(db, m.id, slug=f"topic-{category.value.lower()}")
    s = _make_subtopic(db, t.id, slug=f"sub-{category.value.lower()}")
    return m, t, s


# ----- ModuleRepository -----------------------------------------------------


def test_list_by_category_filters_modules(db_session: Session) -> None:
    _make_module(db_session, category=Category.PROFESSIONAL, slug="prof-1")
    _make_module(db_session, category=Category.PROFESSIONAL, slug="prof-2")
    _make_module(db_session, category=Category.SUB_PROFESSIONAL, slug="sub-1")

    repo = ModuleRepository(db=db_session)
    rows, total = repo.list_by_category(Category.PROFESSIONAL)

    assert total == 2
    assert {m.slug for m in rows} == {"prof-1", "prof-2"}


def test_list_by_category_respects_pagination(db_session: Session) -> None:
    for i in range(5):
        _make_module(
            db_session,
            category=Category.PROFESSIONAL,
            slug=f"prof-{i}",
            order_index=i,
        )

    repo = ModuleRepository(db=db_session)
    page1, total1 = repo.list_by_category(Category.PROFESSIONAL, skip=0, limit=2)
    page2, total2 = repo.list_by_category(Category.PROFESSIONAL, skip=2, limit=2)

    assert total1 == total2 == 5
    assert len(page1) == 2
    assert len(page2) == 2
    # Different rows on each page.
    assert {m.id for m in page1}.isdisjoint({m.id for m in page2})


# ----- TopicRepository ------------------------------------------------------


def test_list_by_module_returns_topics_ordered(db_session: Session) -> None:
    m = _make_module(db_session)
    _make_topic(db_session, m.id, slug="z-last", order_index=10)
    _make_topic(db_session, m.id, slug="a-first", order_index=1)
    _make_topic(db_session, m.id, slug="m-mid", order_index=5)

    repo = TopicRepository(db=db_session)
    topics = repo.list_by_module(m.id)

    assert [t.slug for t in topics] == ["a-first", "m-mid", "z-last"]


def test_list_by_module_excludes_other_modules(db_session: Session) -> None:
    m1 = _make_module(db_session, slug="m1")
    m2 = _make_module(db_session, slug="m2")
    _make_topic(db_session, m1.id, slug="t-in-m1")
    _make_topic(db_session, m2.id, slug="t-in-m2")

    repo = TopicRepository(db=db_session)
    topics = repo.list_by_module(m1.id)

    assert [t.slug for t in topics] == ["t-in-m1"]


# ----- SubtopicRepository ---------------------------------------------------


def test_list_by_topic_returns_subtopics_ordered(db_session: Session) -> None:
    m = _make_module(db_session)
    t = _make_topic(db_session, m.id)
    _make_subtopic(db_session, t.id, slug="z", order_index=10)
    _make_subtopic(db_session, t.id, slug="a", order_index=1)

    repo = SubtopicRepository(db=db_session)
    subtopics = repo.list_by_topic(t.id)

    assert [s.slug for s in subtopics] == ["a", "z"]


# ----- LessonRepository -----------------------------------------------------


def test_get_by_subtopic_id_returns_lesson_or_none(db_session: Session) -> None:
    _, _, s = _seed_hierarchy(db_session)
    repo = LessonRepository(db=db_session)

    assert repo.get_by_subtopic_id(s.id) is None

    lesson = _make_lesson(db_session, s.id)
    found = repo.get_by_subtopic_id(s.id)

    assert found is not None
    assert found.id == lesson.id


# ----- QuestionRepository: SQL gate exclusions ------------------------------


def test_list_active_passing_quality_gate_excludes_inactive(
    db_session: Session,
) -> None:
    _, _, s = _seed_hierarchy(db_session)
    # Use distinct correct_answers + matching options so each row is valid
    # at the JSON layer.
    for opt in ("4", "5", "6"):
        _make_question(
            db_session,
            subtopic_id=s.id,
            topic_id=s.topic_id,
            module_id=1,
            options=[opt, "x", "y"],
            correct_answer=opt,
        )
    _make_question(
        db_session,
        subtopic_id=s.id,
        topic_id=s.topic_id,
        module_id=1,
        is_active=False,
    )

    repo = QuestionRepository(db=db_session)
    rows = repo.list_active_passing_quality_gate(subtopic_id=s.id)

    assert len(rows) == 3


def test_list_active_passing_quality_gate_excludes_empty_stem(
    db_session: Session,
) -> None:
    _, _, s = _seed_hierarchy(db_session)
    _make_question(db_session, subtopic_id=s.id)
    _make_question(db_session, subtopic_id=s.id, stem="   ")

    repo = QuestionRepository(db=db_session)
    rows = repo.list_active_passing_quality_gate(subtopic_id=s.id)

    assert len(rows) == 1


def test_list_active_passing_quality_gate_excludes_no_correct_answer(
    db_session: Session,
) -> None:
    _, _, s = _seed_hierarchy(db_session)
    _make_question(db_session, subtopic_id=s.id)
    _make_question(db_session, subtopic_id=s.id, correct_answer="   ")

    repo = QuestionRepository(db=db_session)
    rows = repo.list_active_passing_quality_gate(subtopic_id=s.id)

    assert len(rows) == 1


def test_list_active_passing_quality_gate_excludes_empty_explanation(
    db_session: Session,
) -> None:
    _, _, s = _seed_hierarchy(db_session)
    _make_question(db_session, subtopic_id=s.id)
    _make_question(db_session, subtopic_id=s.id, explanation="")

    repo = QuestionRepository(db=db_session)
    rows = repo.list_active_passing_quality_gate(subtopic_id=s.id)

    assert len(rows) == 1


def test_list_active_passing_quality_gate_excludes_invalid_difficulty(
    db_session: Session,
) -> None:
    _, _, s = _seed_hierarchy(db_session)
    # The CHECK constraint blocks insert of an invalid difficulty, so we
    # have to disable FK/CHECK by going via raw SQLAlchemy. Easier: insert
    # one valid row, then mutate the persisted row to bypass CHECK
    # (SQLite enforces CHECK on UPDATE too). We can't easily smuggle a bad
    # value into the column, so verify that the CHECK constraint *does*
    # prevent insert — that is the actual safety guarantee. The Python-only
    # test for invalid difficulty lives in ``test_quality_gate.py``.
    from sqlalchemy.exc import IntegrityError

    _make_question(db_session, subtopic_id=s.id)
    with pytest.raises(IntegrityError):
        _make_question(db_session, subtopic_id=s.id, difficulty="BANANAS")
    db_session.rollback()

    repo = QuestionRepository(db=db_session)
    rows = repo.list_active_passing_quality_gate(subtopic_id=s.id)

    assert len(rows) == 1


def test_list_active_passing_quality_gate_excludes_invalid_type(
    db_session: Session,
) -> None:
    """As with difficulty, qtype CHECK prevents insert of garbage values.

    The DB-level guarantee is the relevant test; the Python-level filter
    is exercised in ``test_quality_gate.py``.
    """
    from sqlalchemy.exc import IntegrityError

    _, _, s = _seed_hierarchy(db_session)
    _make_question(db_session, subtopic_id=s.id)
    with pytest.raises(IntegrityError):
        _make_question(db_session, subtopic_id=s.id, qtype="DOODLE")
    db_session.rollback()

    repo = QuestionRepository(db=db_session)
    rows = repo.list_active_passing_quality_gate(subtopic_id=s.id)

    assert len(rows) == 1


def test_list_active_passing_quality_gate_excludes_mc_with_one_option(
    db_session: Session,
) -> None:
    _, _, s = _seed_hierarchy(db_session)
    _make_question(db_session, subtopic_id=s.id)
    _make_question(
        db_session,
        subtopic_id=s.id,
        options=["only"],
        correct_answer="only",
    )

    repo = QuestionRepository(db=db_session)
    rows = repo.list_active_passing_quality_gate(subtopic_id=s.id)

    assert len(rows) == 1


def test_list_active_passing_quality_gate_excludes_mc_with_seven_options(
    db_session: Session,
) -> None:
    _, _, s = _seed_hierarchy(db_session)
    _make_question(db_session, subtopic_id=s.id)
    _make_question(
        db_session,
        subtopic_id=s.id,
        options=["a", "b", "c", "d", "e", "f", "g"],
        correct_answer="a",
    )

    repo = QuestionRepository(db=db_session)
    rows = repo.list_active_passing_quality_gate(subtopic_id=s.id)

    assert len(rows) == 1


def test_list_active_passing_quality_gate_excludes_mc_correct_not_in_options(
    db_session: Session,
) -> None:
    _, _, s = _seed_hierarchy(db_session)
    _make_question(db_session, subtopic_id=s.id)
    _make_question(
        db_session,
        subtopic_id=s.id,
        options=["3", "4", "5", "6"],
        correct_answer="42",
    )

    repo = QuestionRepository(db=db_session)
    rows = repo.list_active_passing_quality_gate(subtopic_id=s.id)

    assert len(rows) == 1


# ----- QuestionRepository: scope filters ------------------------------------


def test_list_active_passing_quality_gate_filters_by_subtopic(
    db_session: Session,
) -> None:
    m = _make_module(db_session)
    t = _make_topic(db_session, m.id)
    s1 = _make_subtopic(db_session, t.id, slug="s1")
    s2 = _make_subtopic(db_session, t.id, slug="s2")
    _make_question(db_session, subtopic_id=s1.id, topic_id=t.id, module_id=m.id)
    _make_question(db_session, subtopic_id=s2.id, topic_id=t.id, module_id=m.id)

    repo = QuestionRepository(db=db_session)
    rows = repo.list_active_passing_quality_gate(subtopic_id=s1.id)

    assert len(rows) == 1
    assert rows[0].subtopic_id == s1.id


def test_list_active_passing_quality_gate_filters_by_module_and_level_scope(
    db_session: Session,
) -> None:
    m = _make_module(db_session)
    t = _make_topic(db_session, m.id)
    s = _make_subtopic(db_session, t.id)

    _make_question(
        db_session,
        subtopic_id=s.id,
        topic_id=t.id,
        module_id=m.id,
        level_scope=LevelScope.SUBTOPIC,
    )
    _make_question(
        db_session,
        subtopic_id=s.id,
        topic_id=t.id,
        module_id=m.id,
        level_scope=LevelScope.TOPIC,
    )
    _make_question(
        db_session,
        subtopic_id=s.id,
        topic_id=t.id,
        module_id=m.id,
        level_scope=LevelScope.MODULE,
    )
    # A question on a different module, same level_scope.
    other_m = _make_module(db_session, slug="other")
    other_t = _make_topic(db_session, other_m.id, slug="ot")
    other_s = _make_subtopic(db_session, other_t.id, slug="os")
    _make_question(
        db_session,
        subtopic_id=other_s.id,
        topic_id=other_t.id,
        module_id=other_m.id,
        level_scope=LevelScope.MODULE,
    )

    repo = QuestionRepository(db=db_session)
    rows = repo.list_active_passing_quality_gate(
        module_id=m.id, level_scope=LevelScope.MODULE
    )

    assert len(rows) == 1
    assert rows[0].module_id == m.id
    assert rows[0].level_scope == LevelScope.MODULE.value


def test_list_active_passing_quality_gate_filters_by_category(
    db_session: Session,
) -> None:
    _, _, s_pro = _seed_hierarchy(db_session, category=Category.PROFESSIONAL)
    _, _, s_sub = _seed_hierarchy(db_session, category=Category.SUB_PROFESSIONAL)
    _make_question(
        db_session,
        subtopic_id=s_pro.id,
        category=Category.PROFESSIONAL,
    )
    _make_question(
        db_session,
        subtopic_id=s_sub.id,
        category=Category.SUB_PROFESSIONAL,
    )

    repo = QuestionRepository(db=db_session)
    rows = repo.list_active_passing_quality_gate(category=Category.PROFESSIONAL)

    assert len(rows) == 1
    assert rows[0].category == Category.PROFESSIONAL.value


# ----- QuestionRepository.log_rejection -------------------------------------


def test_log_rejection_creates_row(db_session: Session) -> None:
    _, _, s = _seed_hierarchy(db_session)
    q = _make_question(db_session, subtopic_id=s.id)

    repo = QuestionRepository(db=db_session)
    log = repo.log_rejection(q.id, RULE_MC_OPTION_COUNT)

    assert log.id is not None
    assert log.question_id == q.id
    assert log.rule == RULE_MC_OPTION_COUNT
    assert log.rejected_at is not None
