"""Reset database and seed with real content only.

Drops old placeholder modules and seeds:
1. Users (admin + learners)
2. Achievements
3. Verbal Ability content (modules, topics, subtopics, lessons, questions)
4. Mock exam configs pointing to the real modules

Usage:
    python scripts/reset_and_seed.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.infrastructure.database.session import SessionLocal, engine
from app.infrastructure.database.base import Base

# Import ALL models so Base.metadata knows every table before create_all
from app.features.users.models import User  # noqa: F401
from app.features.auth.models import Session as AuthSession, LoginAttempt, UserLockout  # noqa: F401
from app.features.otp.models import OTP  # noqa: F401
from app.features.content.models import Module, Topic, Subtopic, Lesson, Question  # noqa: F401
from app.features.quizzes.models import QuizAttempt, QuizAttemptAnswer  # noqa: F401
from app.features.mock_exams.models import MockExamConfig, MockExamAttempt, MockExamAttemptAnswer  # noqa: F401
from app.features.progress.models import LessonCompletion, UserTopicProgress, UserModuleProgress  # noqa: F401
from app.features.xp.models import UserXP, XPEvent  # noqa: F401
from app.features.achievements.models import Achievement, UserAchievement  # noqa: F401
from app.features.audit.models import AuditLog  # noqa: F401

from scripts.seed import seed_database
from scripts.seed_content import seed_content


def main():
    # Recreate all tables (fresh start)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("Database reset complete.")

    session = SessionLocal()
    try:
        # Step 1: Run base seed (users + achievements + placeholder content)
        result = seed_database(session)
        print(f"Base seed: {result.get('status', 'unknown')}")

        # Step 2: Remove placeholder modules and their mock configs
        # The base seed creates "pro-module-1" and "sub-module-1" with fake content
        placeholder_slugs = ["pro-module-1", "sub-module-1"]
        for slug in placeholder_slugs:
            mod = session.query(Module).filter(Module.slug == slug).first()
            if mod:
                # Remove mock config referencing this module
                session.query(MockExamConfig).filter(
                    MockExamConfig.category == mod.category
                ).delete()
                # Delete module (cascades to topics, subtopics, lessons, questions)
                session.delete(mod)
                print(f"  Removed placeholder: {slug}")

        session.commit()

        # Step 3: Seed real content (Verbal Ability for both categories)
        content_result = seed_content(session)
        print(f"Content seed: {content_result.get('status', 'unknown')}")
        print(f"  Questions loaded: {content_result.get('questions_loaded', 0)}")

        # Step 4: Create mock exam configs pointing to real modules
        if content_result.get("modules"):
            for mod_info in content_result["modules"]:
                config = MockExamConfig(
                    category=mod_info["category"],
                    total_questions=50,
                    weights_json={str(mod_info["module_id"]): 50},
                    time_limit_minutes=180,
                    nav_policy="FREE_NAV",
                    pass_threshold=0.80,
                )
                session.add(config)
            session.commit()
            print("  Mock exam configs created for real modules.")

        print("\nDone! The system now shows 'Verbal Ability' modules.")
        print("  Professional learner: learner-pro@cse.local / Learner1Pass!")
        print("  Sub-Professional learner: learner-sub@cse.local / Learner1Pass!")
        print("  Admin: admin@cse.local / Admin1Pass!")

    finally:
        session.close()


if __name__ == "__main__":
    main()
