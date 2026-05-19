"""Seed content loader for Grammar and Correct Usage lessons and question banks.

Loads authored lessons (Markdown → LessonContent JSON) and question banks
into the modules hierarchy for BOTH Professional and Sub-Professional categories.

Hierarchy created:
  Module: "Verbal Ability" (one per category)
    Topic: "Grammar and Correct Usage"
      Subtopic 1: "Subject-Verb Agreement"
        Lesson: parsed from data/seed/lessons/.../subject-verb-agreement/lesson.md
        Questions: loaded from data/seed/questions/.../subject-verb-agreement/questions.json
      Subtopic 2: "Verb Tenses"
        Lesson: parsed from data/seed/lessons/.../verb-tenses/lesson.md
        Questions: loaded from data/seed/questions/.../verb-tenses/questions.json

Usage:
    python -m scripts.seed_content

Requires:
    - Database tables already created (run scripts/seed.py first or ensure migrations applied)
    - Seed files present in data/seed/
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

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
from app.features.users.models import Category
from app.infrastructure.database.base import Base


SEED_BASE = Path(__file__).resolve().parent.parent / "data" / "seed"

# Subtopic 1: Subject-Verb Agreement
SVA_LESSON_PATH = SEED_BASE / "lessons" / "verbal-ability" / "grammar" / "subject-verb-agreement" / "lesson.md"
SVA_QUESTIONS_PATH = SEED_BASE / "questions" / "verbal-ability" / "grammar" / "subject-verb-agreement" / "questions.json"

# Subtopic 2: Verb Tenses
VT_LESSON_PATH = SEED_BASE / "lessons" / "verbal-ability" / "grammar" / "verb-tenses" / "lesson.md"
VT_QUESTIONS_PATH = SEED_BASE / "questions" / "verbal-ability" / "grammar" / "verb-tenses" / "questions.json"

# Legacy aliases for backward compatibility
LESSON_PATH = SVA_LESSON_PATH
QUESTIONS_PATH = SVA_QUESTIONS_PATH


# --- Markdown parser ---

def parse_lesson_markdown(md_text: str) -> dict[str, Any]:
    """Parse lesson markdown into LessonContent JSON structure.

    Expected H2 sections: Explanations, Worked Examples, Key Takeaways, Summary.
    H3 headings under Explanations/Worked Examples become individual entries.
    """
    sections: dict[str, str] = {}
    current_h2 = None
    lines = md_text.split("\n")
    buffer: list[str] = []

    for line in lines:
        if line.startswith("## "):
            if current_h2 is not None:
                sections[current_h2] = "\n".join(buffer).strip()
            current_h2 = line[3:].strip()
            buffer = []
        else:
            buffer.append(line)

    if current_h2 is not None:
        sections[current_h2] = "\n".join(buffer).strip()

    # Parse Explanations (H3 → entries)
    explanations = _parse_h3_entries(sections.get("Explanations", ""))

    # Parse Worked Examples (H3 → entries)
    worked_examples = _parse_h3_entries(sections.get("Worked Examples", ""))

    # Parse Key Takeaways (bullet points)
    key_takeaways = _parse_bullets(sections.get("Key Takeaways", ""))

    # Summary is the raw text
    summary = sections.get("Summary", "").strip()

    return {
        "explanations": [{"title": e[0], "body": e[1]} for e in explanations],
        "worked_examples": [{"title": e[0], "problem": "", "solution": e[1]} for e in worked_examples],
        "key_takeaways": key_takeaways,
        "summary": summary,
    }


def _parse_h3_entries(text: str) -> list[tuple[str, str]]:
    """Split text by H3 headings into (title, body) pairs."""
    entries: list[tuple[str, str]] = []
    current_title = None
    buffer: list[str] = []

    for line in text.split("\n"):
        if line.startswith("### "):
            if current_title is not None:
                entries.append((current_title, "\n".join(buffer).strip()))
            current_title = line[4:].strip()
            buffer = []
        else:
            buffer.append(line)

    if current_title is not None:
        entries.append((current_title, "\n".join(buffer).strip()))

    # If no H3 found, treat entire text as one entry
    if not entries and text.strip():
        entries.append(("Overview", text.strip()))

    return entries


def _parse_bullets(text: str) -> list[str]:
    """Extract bullet points (lines starting with '- ')."""
    bullets = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
    return bullets if bullets else ["No key takeaways provided."]


# --- Difficulty/Category mapping ---

DIFFICULTY_MAP = {
    "Easy": Difficulty.EASY.value,
    "Medium": Difficulty.MEDIUM.value,
    "Hard": Difficulty.HARD.value,
}

CATEGORY_MAP = {
    "Professional": Category.PROFESSIONAL.value,
    "Sub-Professional": Category.SUB_PROFESSIONAL.value,
}


# --- Main seed function ---

def seed_content(session: Session) -> dict[str, Any]:
    """Seed the Verbal Ability / Grammar content for both categories.

    Creates the module hierarchy for BOTH categories and loads lessons
    and questions for all subtopics. Idempotent: skips if the module slug
    already exists.

    Subtopics seeded:
      1. Subject-Verb Agreement (500 questions)
      2. Verb Tenses (500 questions)
    """
    results: dict[str, Any] = {"modules": [], "questions_loaded": 0}

    # Check idempotency
    existing = session.query(Module).filter(
        Module.slug == "verbal-ability-professional"
    ).first()
    if existing is not None:
        return {"status": "already_seeded", "module_id": existing.id}

    # Load source files — Subtopic 1: Subject-Verb Agreement
    if not SVA_LESSON_PATH.exists():
        raise FileNotFoundError(f"Lesson file not found: {SVA_LESSON_PATH}")
    if not SVA_QUESTIONS_PATH.exists():
        raise FileNotFoundError(f"Questions file not found: {SVA_QUESTIONS_PATH}")

    sva_lesson_md = SVA_LESSON_PATH.read_text(encoding="utf-8")
    sva_lesson_content = parse_lesson_markdown(sva_lesson_md)
    sva_questions_raw = json.loads(SVA_QUESTIONS_PATH.read_text(encoding="utf-8"))

    # Load source files — Subtopic 2: Verb Tenses
    if not VT_LESSON_PATH.exists():
        raise FileNotFoundError(f"Lesson file not found: {VT_LESSON_PATH}")
    if not VT_QUESTIONS_PATH.exists():
        raise FileNotFoundError(f"Questions file not found: {VT_QUESTIONS_PATH}")

    vt_lesson_md = VT_LESSON_PATH.read_text(encoding="utf-8")
    vt_lesson_content = parse_lesson_markdown(vt_lesson_md)
    vt_questions_raw = json.loads(VT_QUESTIONS_PATH.read_text(encoding="utf-8"))

    # Define subtopics to seed
    subtopics_data = [
        {
            "slug": "subject-verb-agreement",
            "title": "Subject-Verb Agreement",
            "order_index": 1,
            "lesson_content": sva_lesson_content,
            "questions": sva_questions_raw,
        },
        {
            "slug": "verb-tenses",
            "title": "Verb Tenses",
            "order_index": 2,
            "lesson_content": vt_lesson_content,
            "questions": vt_questions_raw,
        },
    ]

    # Create hierarchy for BOTH categories
    for cat_key, cat_value in [
        ("professional", Category.PROFESSIONAL.value),
        ("sub-professional", Category.SUB_PROFESSIONAL.value),
    ]:
        # Module
        module = Module(
            category=cat_value,
            slug=f"verbal-ability-{cat_key}",
            title="Verbal Ability",
            order_index=10,  # After existing seed modules
            is_published=True,
        )
        session.add(module)
        session.flush()

        # Topic
        topic = Topic(
            module_id=module.id,
            slug="grammar-and-correct-usage",
            title="Grammar and Correct Usage",
            order_index=1,
        )
        session.add(topic)
        session.flush()

        # Seed each subtopic
        for st_data in subtopics_data:
            subtopic = Subtopic(
                topic_id=topic.id,
                slug=st_data["slug"],
                title=st_data["title"],
                order_index=st_data["order_index"],
            )
            session.add(subtopic)
            session.flush()

            # Lesson
            lesson = Lesson(
                subtopic_id=subtopic.id,
                content_json=st_data["lesson_content"],
                status=LessonStatus.PUBLISHED.value,
            )
            session.add(lesson)

            # Questions — load all for this category's subtopic
            for q in st_data["questions"]:
                question = Question(
                    subtopic_id=subtopic.id,
                    topic_id=topic.id,
                    module_id=module.id,
                    category=cat_value,
                    level_scope=LevelScope.SUBTOPIC.value,
                    stem=q["question"],
                    options=q["choices"],
                    correct_answer=q["answer"],
                    explanation=q["explanation"],
                    difficulty=DIFFICULTY_MAP.get(q["difficulty"], Difficulty.EASY.value),
                    qtype=QuestionType.MULTIPLE_CHOICE.value,
                    is_active=True,
                )
                session.add(question)

            results["questions_loaded"] += len(st_data["questions"])

        results["modules"].append({
            "category": cat_value,
            "module_id": module.id,
            "topic_id": topic.id,
        })

    session.commit()
    results["status"] = "seeded"
    return results


def run_standalone() -> None:
    """Run the content seed against the production database."""
    from app.infrastructure.database.session import SessionLocal, engine

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        result = seed_content(session)
        print(f"Content seed result: {json.dumps(result, indent=2)}")
    finally:
        session.close()


if __name__ == "__main__":
    run_standalone()
