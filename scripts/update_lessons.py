"""Update lesson content in-place without wiping user data.

Re-parses all lesson.md files and updates the content_json for existing
lessons. Does NOT touch users, progress, scores, or any other tables.

Usage:
    python scripts/update_lessons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.infrastructure.database.session import SessionLocal, engine
from app.infrastructure.database.base import Base
from app.features.content.models import Lesson, Subtopic, Topic, Module
from scripts.seed_content import (
    parse_lesson_markdown,
    GRAMMAR_LESSONS,
    SUBTOPICS_CONFIG,
)


def main() -> None:
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        updated = 0
        for slug, title, folder in SUBTOPICS_CONFIG:
            lesson_path = GRAMMAR_LESSONS / folder / "lesson.md"
            if not lesson_path.exists():
                print(f"  SKIP {slug}: no lesson.md found")
                continue

            md_text = lesson_path.read_text(encoding="utf-8")
            new_content = parse_lesson_markdown(md_text)

            # Find all lessons for this subtopic (both categories)
            subtopics = session.query(Subtopic).filter(
                Subtopic.slug == slug
            ).all()

            for st in subtopics:
                lesson = session.query(Lesson).filter(
                    Lesson.subtopic_id == st.id
                ).first()
                if lesson:
                    lesson.content_json = new_content
                    updated += 1
                    print(f"  Updated: {slug} (subtopic_id={st.id})")

        session.commit()
        print(f"\nDone. Updated {updated} lesson(s).")
    finally:
        session.close()


if __name__ == "__main__":
    main()
