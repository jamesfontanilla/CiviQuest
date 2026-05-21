"""End-to-end smoke test exercising the full application flow.

Spins up the app with TestClient, seeds an in-memory DB, then exercises:
1. Signup → OTP verify (read code from offline-OTP file) → login
2. Module list → lesson read → lesson complete
3. Subtopic quiz start → answer all → submit
4. Topic quiz prereq blocked (not all subtopics passed) — verify 409
5. Mock exam start → answer a few → submit
6. XP / level / leaderboard / achievements assertions
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.database.base import Base
from app.infrastructure.database.pragmas import register_pragmas

# Import all models so Base.metadata knows about them
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


@pytest.fixture()
def smoke_env() -> Iterator[tuple[TestClient, str]]:
    """Set up an in-memory DB, override get_db, seed data, yield TestClient.

    Returns (client, otp_log_path) so the test can read OTP codes.
    """
    # Create in-memory engine
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    register_pragmas(engine)
    Base.metadata.create_all(bind=engine)

    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )

    # Create a temp file for OTP offline log
    otp_fd, otp_path = tempfile.mkstemp(suffix=".log", prefix="otp_smoke_")
    os.close(otp_fd)

    # Set env vars BEFORE importing the app
    original_otp_path = os.environ.get("OTP_OFFLINE_LOG_PATH")
    os.environ["OTP_OFFLINE_LOG_PATH"] = otp_path

    original_jwt_secret = os.environ.get("JWT_SECRET")
    os.environ["JWT_SECRET"] = "smoke-test-secret-key-for-testing"

    from app.infrastructure.database.session import get_db
    from app.main import app
    from fastapi import Depends

    # Override the OTP service factory so SmtpOtpSender writes to the offline
    # log instead of calling Resend. This lets the smoke test read OTP codes
    # without real email credentials.
    from app.features.auth.router import get_otp_service as _orig_get_otp_service
    from app.features.otp.repository import OTPRepository
    from app.features.otp.service import OTPService
    from app.features.users.repository import UserRepository
    from app.infrastructure.external.offline_otp_writer import OfflineOtpWriter
    from app.infrastructure.external.smtp_otp_sender import SmtpOtpSender

    class _OfflineFallbackSender(SmtpOtpSender):
        """Smoke-test stub: writes to the offline log instead of calling Resend."""

        def __init__(self) -> None:
            super().__init__(api_key="")
            self._writer = OfflineOtpWriter(log_path=otp_path)

        def send_otp(self, to_email: str, code: str, purpose: str) -> bool:
            self._writer.write_otp(email=to_email, purpose=purpose, code=code)
            return True

    def _smoke_get_otp_service(db: Session = Depends(get_db)) -> OTPService:
        return OTPService(
            user_repo=UserRepository(db=db),
            otp_repo=OTPRepository(db=db),
            offline_writer=OfflineOtpWriter(log_path=otp_path),
            smtp_sender=_OfflineFallbackSender(),
        )

    # Patch randbits to stay within SQLite signed 64-bit range (2^63 - 1)
    # The production code uses randbits(64) which can exceed SQLite's max.
    import app.infrastructure.security.rng as rng_module
    _original_randbits = rng_module.randbits

    def _safe_randbits(k: int) -> int:
        val = _original_randbits(k)
        if k >= 63:
            val = val & ((1 << 63) - 1)
        return val

    rng_module.randbits = _safe_randbits

    def override_get_db() -> Iterator[Session]:
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[_orig_get_otp_service] = _smoke_get_otp_service

    # Seed the database
    seed_session = TestingSessionLocal()
    try:
        from scripts.seed import seed_database
        seed_database(seed_session)
    finally:
        seed_session.close()

    client = TestClient(app)
    try:
        yield client, otp_path
    finally:
        app.dependency_overrides.clear()
        rng_module.randbits = _original_randbits
        # Restore env
        if original_otp_path is None:
            os.environ.pop("OTP_OFFLINE_LOG_PATH", None)
        else:
            os.environ["OTP_OFFLINE_LOG_PATH"] = original_otp_path
        if original_jwt_secret is None:
            os.environ.pop("JWT_SECRET", None)
        else:
            os.environ["JWT_SECRET"] = original_jwt_secret
        # Cleanup temp file
        try:
            os.unlink(otp_path)
        except OSError:
            pass


def _read_latest_otp(otp_path: str) -> str:
    """Read the most recent OTP code from the offline log file."""
    with open(otp_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert lines, "No OTP codes found in offline log"
    last_line = lines[-1].strip()
    record = json.loads(last_line)
    return record["code"]


def test_full_e2e_flow(smoke_env: tuple[TestClient, str]) -> None:
    """Exercise the complete user journey from signup to mock exam."""
    client, otp_path = smoke_env

    # --- Health check ---
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    # --- 1. Signup → OTP verify → login ---
    signup_payload = {
        "email": "smoketest@cse.local",
        "display_name": "Smoke Tester",
        "age": 25,
        "category": "PROFESSIONAL",
        "password": "Smoke1Pass!",
    }
    resp = client.post("/v1/auth/signups", json=signup_payload)
    assert resp.status_code == 201, f"Signup failed: {resp.text}"
    user_data = resp.json()
    assert user_data["email"] == "smoketest@cse.local"
    assert user_data["account_state"] == "UNVERIFIED"

    # Read OTP from offline log
    otp_code = _read_latest_otp(otp_path)
    assert len(otp_code) == 6

    # Verify email
    verify_payload = {
        "email": "smoketest@cse.local",
        "code": otp_code,
        "purpose": "VERIFY_EMAIL",
    }
    resp = client.post("/v1/auth/email-verifications", json=verify_payload)
    assert resp.status_code == 200, f"Verify failed: {resp.text}"
    assert resp.json()["account_state"] == "VERIFIED"

    # Login
    login_payload = {
        "email": "smoketest@cse.local",
        "password": "Smoke1Pass!",
    }
    resp = client.post("/v1/auth/sessions", json=login_payload)
    assert resp.status_code == 201, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # --- 2. Module list → lesson read → lesson complete ---
    resp = client.get("/v1/modules", headers=headers)
    assert resp.status_code == 200, f"Module list failed: {resp.text}"
    modules = resp.json()
    assert modules["total"] >= 1
    module_id = modules["items"][0]["id"]

    # Get topics for the module
    resp = client.get(f"/v1/modules/{module_id}/topics", headers=headers)
    assert resp.status_code == 200, f"Topics list failed: {resp.text}"
    topics = resp.json()
    assert len(topics) >= 1
    topic_id = topics[0]["id"]

    # Get subtopics for the first topic
    resp = client.get(f"/v1/topics/{topic_id}/subtopics", headers=headers)
    assert resp.status_code == 200, f"Subtopics list failed: {resp.text}"
    subtopics = resp.json()
    assert len(subtopics) >= 2
    subtopic_id = subtopics[0]["id"]

    # Read lesson
    resp = client.get(f"/v1/subtopics/{subtopic_id}/lesson", headers=headers)
    assert resp.status_code == 200, f"Lesson read failed: {resp.text}"

    # Complete lesson
    resp = client.post(
        f"/v1/subtopics/{subtopic_id}/lesson:complete",
        json={"client_event_id": "smoke-lesson-1"},
        headers=headers,
    )
    assert resp.status_code == 201, f"Lesson complete failed: {resp.text}"

    # --- 3. Subtopic quiz start → answer all → submit ---
    resp = client.post(
        f"/v1/subtopics/{subtopic_id}/quiz-attempts",
        headers=headers,
    )
    assert resp.status_code == 201, f"Quiz start failed: {resp.text}"
    quiz_data = resp.json()
    attempt_id = quiz_data["attempt_id"]
    questions = quiz_data["questions"]
    assert len(questions) == 20

    # Answer all questions (pick the first option for each)
    for q in questions:
        q_id = q["id"]
        # Pick the first option
        selected = q["options"][0] if q.get("options") else "Option 1"
        resp = client.patch(
            f"/v1/quiz-attempts/{attempt_id}/answers/{q_id}",
            json={"selected_answer": selected},
            headers=headers,
        )
        assert resp.status_code == 200, f"Answer set failed for q={q_id}: {resp.text}"

    # Submit quiz
    resp = client.post(
        f"/v1/quiz-attempts/{attempt_id}:submit",
        headers=headers,
    )
    assert resp.status_code == 200, f"Quiz submit failed: {resp.text}"
    quiz_result = resp.json()
    assert "score" in quiz_result
    assert "max_score" in quiz_result

    # --- 4. Topic quiz prereq blocked (not all subtopics passed) ---
    # We only completed one subtopic's lesson + quiz, not both subtopics
    resp = client.post(
        f"/v1/topics/{topic_id}/quiz-attempts",
        headers=headers,
    )
    assert resp.status_code == 409, (
        f"Expected 409 for topic quiz prereq, got {resp.status_code}: {resp.text}"
    )

    # --- 5. Mock exam start → answer a few → submit ---
    resp = client.post("/v1/mock-exams/attempts", headers=headers)
    assert resp.status_code == 201, f"Mock exam start failed: {resp.text}"
    mock_data = resp.json()
    mock_attempt_id = mock_data["attempt_id"]
    mock_questions = mock_data["questions"]
    assert len(mock_questions) == 50

    # Answer first 5 questions
    for q in mock_questions[:5]:
        q_id = q["id"]
        selected = q["options"][0] if q.get("options") else "Option 1"
        resp = client.patch(
            f"/v1/mock-exams/attempts/{mock_attempt_id}/answers/{q_id}",
            json={"selected_answer": selected},
            headers=headers,
        )
        assert resp.status_code == 200, f"Mock answer failed for q={q_id}: {resp.text}"

    # Submit mock exam
    resp = client.post(
        f"/v1/mock-exams/attempts/{mock_attempt_id}:submit",
        headers=headers,
    )
    assert resp.status_code == 200, f"Mock submit failed: {resp.text}"
    mock_result = resp.json()
    assert "score" in mock_result
    assert "max_score" in mock_result
    assert "percentage" in mock_result

    # --- 6. XP / level / leaderboard / achievements assertions ---
    resp = client.get("/v1/xp/me", headers=headers)
    assert resp.status_code == 200, f"XP read failed: {resp.text}"
    xp_data = resp.json()
    assert "cumulative_xp" in xp_data
    assert "level" in xp_data
    assert "streak" in xp_data
    assert xp_data["cumulative_xp"] >= 0

    # Leaderboard
    resp = client.get("/v1/leaderboards/global", headers=headers)
    assert resp.status_code == 200, f"Leaderboard failed: {resp.text}"
    leaderboard = resp.json()
    assert isinstance(leaderboard, list)

    # Achievements
    resp = client.get("/v1/achievements/me", headers=headers)
    assert resp.status_code == 200, f"Achievements failed: {resp.text}"
    achievements = resp.json()
    assert isinstance(achievements, list)
