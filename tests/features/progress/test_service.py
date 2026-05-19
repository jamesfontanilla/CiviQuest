"""Service tests for the progress slice (Task 8.2).

Per ``testing-standards.md`` the service layer is exercised against
mocked repositories. The tests cover:

* ``complete_lesson`` happy path (awards 20 XP, persists, returns row).
* ``complete_lesson`` idempotency — by ``client_event_id`` and by
  ``(user, lesson)``. Both branches return ``awarded_xp=0``.
* ``complete_lesson`` 403 paths — missing subtopic, missing lesson,
  DRAFT/INCOMPLETE lesson.
* ``complete_lesson`` honours a soft XP service stub when present.
* ``get_snapshot`` returns completed lesson ids and the placeholder
  fields without crashing when the XP service is missing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, status

from app.features.content.models import LessonStatus, Lesson, Subtopic
from app.features.content.repository import (
    LessonRepository,
    SubtopicRepository,
)
from app.features.progress.models import LessonCompletion
from app.features.progress.repository import ProgressRepository
from app.features.progress.schemas import LessonCompleteRequest
from app.features.progress.service import ProgressService
from app.features.users.models import AccountState, Category, Role, User


# --- factories --------------------------------------------------------------


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "id": 1,
        "email": "alice@example.com",
        "display_name": "Alice",
        "age": 25,
        "category": Category.PROFESSIONAL.value,
        "role": Role.LEARNER.value,
        "account_state": AccountState.VERIFIED.value,
        "is_banned": False,
        "tz_name": "UTC",
        "password_hash": "x",
        "cross_category_preview": False,
    }
    return User(**{**defaults, **overrides})


def _make_subtopic(**overrides: object) -> Subtopic:
    defaults: dict[str, object] = {
        "id": 30,
        "topic_id": 20,
        "slug": "linear",
        "title": "Linear",
        "order_index": 0,
    }
    return Subtopic(**{**defaults, **overrides})


def _make_lesson(**overrides: object) -> Lesson:
    defaults: dict[str, object] = {
        "id": 40,
        "subtopic_id": 30,
        "content_json": {
            "explanations": [{"heading": "I", "body": "b"}],
            "worked_examples": [{"title": "T", "body": "b"}],
            "key_takeaways": ["k"],
            "summary": "s",
        },
        "status": LessonStatus.PUBLISHED.value,
    }
    return Lesson(**{**defaults, **overrides})


def _make_completion(**overrides: object) -> LessonCompletion:
    defaults: dict[str, object] = {
        "id": 100,
        "user_id": 1,
        "lesson_id": 40,
        "completed_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "client_event_id": None,
    }
    return LessonCompletion(**{**defaults, **overrides})


def _build_service(
    *,
    progress_repo: MagicMock | None = None,
    lesson_repo: MagicMock | None = None,
    subtopic_repo: MagicMock | None = None,
) -> tuple[ProgressService, MagicMock, MagicMock, MagicMock]:
    pr = progress_repo or MagicMock(spec=ProgressRepository)
    lr = lesson_repo or MagicMock(spec=LessonRepository)
    sr = subtopic_repo or MagicMock(spec=SubtopicRepository)
    return (
        ProgressService(progress_repo=pr, lesson_repo=lr, subtopic_repo=sr),
        pr,
        lr,
        sr,
    )


# --- complete_lesson: happy path ------------------------------------------


def test_complete_lesson_happy_path_returns_awarded_xp_20() -> None:
    user = _make_user()
    subtopic = _make_subtopic()
    lesson = _make_lesson()
    persisted = _make_completion(
        user_id=user.id,
        lesson_id=lesson.id,
        completed_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
    )

    service, pr, lr, sr = _build_service()
    sr.get.return_value = subtopic
    lr.get_by_subtopic_id.return_value = lesson
    pr.get_by_client_event_id.return_value = None
    pr.get_lesson_completion.return_value = None
    pr.mark_lesson_complete.return_value = persisted

    response = service.complete_lesson(
        user=user,
        subtopic_id=subtopic.id,
        payload=LessonCompleteRequest(),
    )

    assert response.awarded_xp == 20
    assert response.lesson_id == lesson.id
    assert response.user_id == user.id
    pr.mark_lesson_complete.assert_called_once()
    # Persistence happens before the response — the call was made.
    assert pr.mark_lesson_complete.call_args.kwargs["user_id"] == user.id
    assert pr.mark_lesson_complete.call_args.kwargs["lesson_id"] == lesson.id


def test_complete_lesson_uses_now_when_payload_lacks_completed_at() -> None:
    user = _make_user()
    subtopic = _make_subtopic()
    lesson = _make_lesson()
    pinned_now = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    persisted = _make_completion(completed_at=pinned_now)

    service, pr, lr, sr = _build_service()
    sr.get.return_value = subtopic
    lr.get_by_subtopic_id.return_value = lesson
    pr.get_by_client_event_id.return_value = None
    pr.get_lesson_completion.return_value = None
    pr.mark_lesson_complete.return_value = persisted

    service.complete_lesson(
        user=user,
        subtopic_id=subtopic.id,
        payload=LessonCompleteRequest(),
        now=pinned_now,
    )

    assert pr.mark_lesson_complete.call_args.kwargs["completed_at"] == pinned_now


def test_complete_lesson_prefers_payload_completed_at_over_now() -> None:
    """Offline replay path: client-provided timestamp wins over server now."""
    user = _make_user()
    subtopic = _make_subtopic()
    lesson = _make_lesson()
    client_when = datetime(2024, 12, 31, tzinfo=timezone.utc)
    server_now = datetime(2025, 6, 1, tzinfo=timezone.utc)
    persisted = _make_completion(completed_at=client_when)

    service, pr, lr, sr = _build_service()
    sr.get.return_value = subtopic
    lr.get_by_subtopic_id.return_value = lesson
    pr.get_by_client_event_id.return_value = None
    pr.get_lesson_completion.return_value = None
    pr.mark_lesson_complete.return_value = persisted

    service.complete_lesson(
        user=user,
        subtopic_id=subtopic.id,
        payload=LessonCompleteRequest(completed_at=client_when),
        now=server_now,
    )

    assert (
        pr.mark_lesson_complete.call_args.kwargs["completed_at"] == client_when
    )


# --- complete_lesson: idempotency by client_event_id ----------------------


def test_complete_lesson_returns_zero_xp_on_client_event_id_replay() -> None:
    user = _make_user()
    prior = _make_completion(
        user_id=user.id,
        lesson_id=40,
        client_event_id="evt-replay",
        completed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    service, pr, lr, sr = _build_service()
    pr.get_by_client_event_id.return_value = prior

    response = service.complete_lesson(
        user=user,
        subtopic_id=30,
        payload=LessonCompleteRequest(client_event_id="evt-replay"),
    )

    assert response.awarded_xp == 0
    assert response.lesson_id == prior.lesson_id
    # No persistence on replay.
    pr.mark_lesson_complete.assert_not_called()
    # The lesson lookup is also skipped — fast path.
    sr.get.assert_not_called()
    lr.get_by_subtopic_id.assert_not_called()


def test_complete_lesson_replay_for_other_user_falls_through() -> None:
    """A prior client_event_id on a different user means the current
    request is a genuinely-new completion, not a replay."""
    user = _make_user(id=2)
    subtopic = _make_subtopic()
    lesson = _make_lesson()
    other_users_prior = _make_completion(user_id=99, lesson_id=lesson.id)
    persisted = _make_completion(user_id=user.id, lesson_id=lesson.id)

    service, pr, lr, sr = _build_service()
    pr.get_by_client_event_id.return_value = other_users_prior
    sr.get.return_value = subtopic
    lr.get_by_subtopic_id.return_value = lesson
    pr.get_lesson_completion.return_value = None
    pr.mark_lesson_complete.return_value = persisted

    response = service.complete_lesson(
        user=user,
        subtopic_id=subtopic.id,
        payload=LessonCompleteRequest(client_event_id="other-evt"),
    )

    # Treated as a new request — full XP awarded.
    assert response.awarded_xp == 20
    pr.mark_lesson_complete.assert_called_once()


# --- complete_lesson: idempotency by (user, lesson) -----------------------


def test_complete_lesson_returns_zero_xp_on_duplicate_user_lesson() -> None:
    user = _make_user()
    subtopic = _make_subtopic()
    lesson = _make_lesson()
    existing = _make_completion(
        user_id=user.id,
        lesson_id=lesson.id,
        completed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    service, pr, lr, sr = _build_service()
    sr.get.return_value = subtopic
    lr.get_by_subtopic_id.return_value = lesson
    pr.get_by_client_event_id.return_value = None
    pr.get_lesson_completion.return_value = existing

    response = service.complete_lesson(
        user=user,
        subtopic_id=subtopic.id,
        payload=LessonCompleteRequest(),
    )

    assert response.awarded_xp == 0
    assert response.lesson_id == lesson.id
    pr.mark_lesson_complete.assert_not_called()


# --- complete_lesson: 403 paths -------------------------------------------


def test_complete_lesson_403_for_unknown_subtopic() -> None:
    service, pr, lr, sr = _build_service()
    pr.get_by_client_event_id.return_value = None
    sr.get.return_value = None  # subtopic missing

    with pytest.raises(HTTPException) as exc_info:
        service.complete_lesson(
            user=_make_user(),
            subtopic_id=9999,
            payload=LessonCompleteRequest(),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "forbidden"
    pr.mark_lesson_complete.assert_not_called()


def test_complete_lesson_403_for_missing_lesson_row() -> None:
    service, pr, lr, sr = _build_service()
    pr.get_by_client_event_id.return_value = None
    sr.get.return_value = _make_subtopic()
    lr.get_by_subtopic_id.return_value = None  # no lesson attached

    with pytest.raises(HTTPException) as exc_info:
        service.complete_lesson(
            user=_make_user(),
            subtopic_id=30,
            payload=LessonCompleteRequest(),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    pr.mark_lesson_complete.assert_not_called()


def test_complete_lesson_403_for_draft_lesson() -> None:
    """Req 6.4 — only PUBLISHED lessons reach learners. DRAFT -> 403."""
    service, pr, lr, sr = _build_service()
    pr.get_by_client_event_id.return_value = None
    sr.get.return_value = _make_subtopic()
    lr.get_by_subtopic_id.return_value = _make_lesson(
        status=LessonStatus.DRAFT.value
    )

    with pytest.raises(HTTPException) as exc_info:
        service.complete_lesson(
            user=_make_user(),
            subtopic_id=30,
            payload=LessonCompleteRequest(),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


def test_complete_lesson_403_for_incomplete_lesson() -> None:
    """Req 6.4 — INCOMPLETE lessons are hidden from learners."""
    service, pr, lr, sr = _build_service()
    pr.get_by_client_event_id.return_value = None
    sr.get.return_value = _make_subtopic()
    lr.get_by_subtopic_id.return_value = _make_lesson(
        status=LessonStatus.INCOMPLETE.value
    )

    with pytest.raises(HTTPException) as exc_info:
        service.complete_lesson(
            user=_make_user(),
            subtopic_id=30,
            payload=LessonCompleteRequest(),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


# --- complete_lesson: soft XP service hook --------------------------------


def test_complete_lesson_does_not_crash_when_xp_service_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The MVP soft-import path: ``XPService`` is None, ``awarded_xp`` is
    still 20 by contract. Locks down the soft-import seam against
    accidental tightening."""
    from app.features.progress import service as service_module

    monkeypatch.setattr(service_module, "XPService", None, raising=False)

    user = _make_user()
    persisted = _make_completion(user_id=user.id, lesson_id=40)
    service, pr, lr, sr = _build_service()
    pr.get_by_client_event_id.return_value = None
    sr.get.return_value = _make_subtopic()
    lr.get_by_subtopic_id.return_value = _make_lesson()
    pr.get_lesson_completion.return_value = None
    pr.mark_lesson_complete.return_value = persisted

    response = service.complete_lesson(
        user=user, subtopic_id=30, payload=LessonCompleteRequest()
    )

    assert response.awarded_xp == 20


def test_complete_lesson_persists_before_returning_response() -> None:
    """Req 14.1: persistence must happen before the response is built.

    We can verify the order by checking that the return value's
    ``completed_at`` is the value coming from the persisted row, not the
    payload — the response is built from the row, so the row must
    already be created.
    """
    user = _make_user()
    persisted_when = datetime(2025, 3, 14, tzinfo=timezone.utc)
    persisted = _make_completion(
        user_id=user.id, lesson_id=40, completed_at=persisted_when
    )

    service, pr, lr, sr = _build_service()
    pr.get_by_client_event_id.return_value = None
    sr.get.return_value = _make_subtopic()
    lr.get_by_subtopic_id.return_value = _make_lesson()
    pr.get_lesson_completion.return_value = None
    pr.mark_lesson_complete.return_value = persisted

    response = service.complete_lesson(
        user=user,
        subtopic_id=30,
        payload=LessonCompleteRequest(
            completed_at=datetime(2099, 1, 1, tzinfo=timezone.utc)
        ),
    )

    # Response field comes from the persisted row, confirming persist-then-respond.
    assert response.completed_at == persisted_when


# --- get_snapshot ---------------------------------------------------------


def test_get_snapshot_returns_completed_lesson_ids() -> None:
    user = _make_user()
    completions = [
        _make_completion(id=1, user_id=user.id, lesson_id=10),
        _make_completion(id=2, user_id=user.id, lesson_id=20),
        _make_completion(id=3, user_id=user.id, lesson_id=30),
    ]

    service, pr, _, _ = _build_service()
    pr.list_completions_for_user.return_value = completions

    snapshot = service.get_snapshot(user)

    assert snapshot.completed_lesson_ids == [10, 20, 30]
    pr.list_completions_for_user.assert_called_once_with(user.id)


def test_get_snapshot_returns_placeholder_fields() -> None:
    """Until Task 9.x lands, XP / level / streak / in-progress lists
    default to safe zero/empty values without crashing."""
    user = _make_user()
    service, pr, _, _ = _build_service()
    pr.list_completions_for_user.return_value = []

    snapshot = service.get_snapshot(user)

    assert snapshot.completed_lesson_ids == []
    assert snapshot.in_progress_quizzes == []
    assert snapshot.in_progress_mock_attempts == []
    assert snapshot.cumulative_xp == 0
    assert snapshot.level == 0
    assert snapshot.streak == 0


def test_get_snapshot_does_not_crash_with_xp_service_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same soft-import seam as ``complete_lesson``."""
    from app.features.progress import service as service_module

    monkeypatch.setattr(service_module, "XPService", None, raising=False)

    user = _make_user()
    service, pr, _, _ = _build_service()
    pr.list_completions_for_user.return_value = []

    # Should not raise.
    snapshot = service.get_snapshot(user)

    assert snapshot.cumulative_xp == 0



# --- get_snapshot: in-progress mock attempts (Req 14.2, 14.3) -------------


def test_get_snapshot_surfaces_in_progress_mock_attempt() -> None:
    """Req 14.2: snapshot includes in-progress mock attempts."""
    from datetime import datetime, timezone, timedelta

    from app.features.mock_exams.models import (
        MockExamAttempt,
        MockExamAttemptStatus,
    )
    from app.features.mock_exams.repository import MockExamRepository

    user = _make_user()
    started = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    attempt = MockExamAttempt(
        id=42,
        user_id=user.id,
        category="PROFESSIONAL",
        status=MockExamAttemptStatus.IN_PROGRESS.value,
        started_at=started,
        max_score=50,
        seed=1,
        focus_loss_events=[],
        nav_policy="LINEAR_NO_REVISIT",
        time_limit_minutes=180,
    )

    pr = MagicMock(spec=ProgressRepository)
    pr.list_completions_for_user.return_value = []
    mock_repo = MagicMock(spec=MockExamRepository)
    mock_repo.get_in_progress_for_user.return_value = attempt

    service = ProgressService(
        progress_repo=pr,
        lesson_repo=MagicMock(spec=LessonRepository),
        subtopic_repo=MagicMock(spec=SubtopicRepository),
        mock_repo=mock_repo,
    )

    snapshot = service.get_snapshot(
        user, now=started + timedelta(minutes=10)
    )

    assert len(snapshot.in_progress_mock_attempts) == 1
    entry = snapshot.in_progress_mock_attempts[0]
    assert entry["id"] == 42
    assert entry["category"] == "PROFESSIONAL"
    assert entry["remaining_seconds"] == 170 * 60


def test_get_snapshot_auto_submits_expired_mock_attempt() -> None:
    """Req 14.3: an expired in-progress attempt is auto-submitted on
    snapshot read; the snapshot does not surface it."""
    from datetime import datetime, timezone, timedelta

    from app.features.mock_exams.models import (
        MockExamAttempt,
        MockExamAttemptStatus,
        MockExamSubmissionMode,
    )
    from app.features.mock_exams.repository import MockExamRepository

    user = _make_user()
    started = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    attempt = MockExamAttempt(
        id=42,
        user_id=user.id,
        category="PROFESSIONAL",
        status=MockExamAttemptStatus.IN_PROGRESS.value,
        started_at=started,
        max_score=50,
        seed=1,
        focus_loss_events=[],
        nav_policy="LINEAR_NO_REVISIT",
        time_limit_minutes=180,
    )

    pr = MagicMock(spec=ProgressRepository)
    pr.list_completions_for_user.return_value = []
    mock_repo = MagicMock(spec=MockExamRepository)
    mock_repo.get_in_progress_for_user.return_value = attempt
    mock_repo.list_attempt_answers.return_value = []

    service = ProgressService(
        progress_repo=pr,
        lesson_repo=MagicMock(spec=LessonRepository),
        subtopic_repo=MagicMock(spec=SubtopicRepository),
        mock_repo=mock_repo,
    )

    snapshot = service.get_snapshot(
        user, now=started + timedelta(minutes=200)
    )

    assert snapshot.in_progress_mock_attempts == []
    mock_repo.submit_attempt.assert_called_once()
    submit_kwargs = mock_repo.submit_attempt.call_args.kwargs
    assert (
        submit_kwargs["submission_mode"]
        == MockExamSubmissionMode.AUTO_SUBMIT
    )


def test_get_snapshot_without_mock_repo_returns_empty_list() -> None:
    """Backwards-compat: snapshot still works without a mock_repo."""
    user = _make_user()
    pr = MagicMock(spec=ProgressRepository)
    pr.list_completions_for_user.return_value = []

    service = ProgressService(
        progress_repo=pr,
        lesson_repo=MagicMock(spec=LessonRepository),
        subtopic_repo=MagicMock(spec=SubtopicRepository),
    )

    snapshot = service.get_snapshot(user)

    assert snapshot.in_progress_mock_attempts == []
