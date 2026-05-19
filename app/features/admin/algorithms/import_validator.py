"""Import referential-integrity validator per design A10 (Req 24.2, 24.3, 16.4).

Validates that:
- No duplicate question ids within the import artifact
- All FK references close within the artifact (subtopic->topic, topic->module, etc.)
- Atomic commit on success; full rollback on any error
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.features.content.models import (
    Lesson,
    Module,
    Question,
    Subtopic,
    Topic,
)


def validate_import(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate referential integrity of an import artifact.

    Returns a list of errors. Empty list means the artifact is valid.
    Each error is a dict with 'type' and 'detail' keys.
    """
    errors: list[dict[str, Any]] = []

    modules = data.get("modules", [])
    topics = data.get("topics", [])
    subtopics = data.get("subtopics", [])
    lessons = data.get("lessons", [])
    questions = data.get("questions", [])

    # Build id sets for FK closure check
    module_ids = {m.get("id") for m in modules if m.get("id") is not None}
    topic_ids = {t.get("id") for t in topics if t.get("id") is not None}
    subtopic_ids = {s.get("id") for s in subtopics if s.get("id") is not None}

    # Check duplicate question ids (Req 16.4)
    seen_q_ids: set[int] = set()
    for q in questions:
        qid = q.get("id")
        if qid is not None:
            if qid in seen_q_ids:
                errors.append({
                    "type": "DUPLICATE_QUESTION_ID",
                    "detail": f"Duplicate question id: {qid}",
                })
            seen_q_ids.add(qid)

    # FK closure: topics -> modules
    for t in topics:
        mid = t.get("module_id")
        if mid is not None and mid not in module_ids:
            errors.append({
                "type": "FK_VIOLATION",
                "detail": f"Topic {t.get('id')} references non-existent module {mid}",
            })

    # FK closure: subtopics -> topics
    for s in subtopics:
        tid = s.get("topic_id")
        if tid is not None and tid not in topic_ids:
            errors.append({
                "type": "FK_VIOLATION",
                "detail": f"Subtopic {s.get('id')} references non-existent topic {tid}",
            })

    # FK closure: lessons -> subtopics
    for l in lessons:
        sid = l.get("subtopic_id")
        if sid is not None and sid not in subtopic_ids:
            errors.append({
                "type": "FK_VIOLATION",
                "detail": f"Lesson {l.get('id')} references non-existent subtopic {sid}",
            })

    # FK closure: questions -> subtopics
    for q in questions:
        sid = q.get("subtopic_id")
        if sid is not None and sid not in subtopic_ids:
            errors.append({
                "type": "FK_VIOLATION",
                "detail": f"Question {q.get('id')} references non-existent subtopic {sid}",
            })

    return errors


def apply_import(db: Session, data: dict[str, Any]) -> None:
    """Apply a validated import artifact to the database.

    Caller must have already validated via validate_import().
    This runs within the caller's transaction context.
    """
    modules = data.get("modules", [])
    topics = data.get("topics", [])
    subtopics = data.get("subtopics", [])
    lessons = data.get("lessons", [])
    questions = data.get("questions", [])

    # Insert modules
    for m in modules:
        obj = Module(
            id=m.get("id"),
            category=m["category"],
            slug=m["slug"],
            title=m["title"],
            order_index=m.get("order_index", 0),
            is_published=m.get("is_published", True),
        )
        db.merge(obj)

    db.flush()

    # Insert topics
    for t in topics:
        obj = Topic(
            id=t.get("id"),
            module_id=t["module_id"],
            slug=t["slug"],
            title=t["title"],
            order_index=t.get("order_index", 0),
        )
        db.merge(obj)

    db.flush()

    # Insert subtopics
    for s in subtopics:
        obj = Subtopic(
            id=s.get("id"),
            topic_id=s["topic_id"],
            slug=s["slug"],
            title=s["title"],
            order_index=s.get("order_index", 0),
        )
        db.merge(obj)

    db.flush()

    # Insert lessons
    for l in lessons:
        obj = Lesson(
            id=l.get("id"),
            subtopic_id=l["subtopic_id"],
            content_json=l["content_json"],
            status=l.get("status", "DRAFT"),
        )
        db.merge(obj)

    db.flush()

    # Insert questions
    for q in questions:
        obj = Question(
            id=q.get("id"),
            subtopic_id=q["subtopic_id"],
            topic_id=q.get("topic_id", 0),
            module_id=q.get("module_id", 0),
            category=q.get("category", "PROFESSIONAL"),
            level_scope=q.get("level_scope", "SUBTOPIC"),
            stem=q["stem"],
            options=q.get("options"),
            correct_answer=q["correct_answer"],
            explanation=q["explanation"],
            difficulty=q.get("difficulty", "MEDIUM"),
            qtype=q.get("qtype", "MULTIPLE_CHOICE"),
            is_active=q.get("is_active", True),
        )
        db.merge(obj)

    db.flush()
