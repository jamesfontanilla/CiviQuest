"""Pydantic schemas for the progress slice.

Shapes:

- :class:`LessonCompleteRequest` — POST body for the lesson-complete
  endpoint. ``client_event_id`` is the offline-sync idempotency key
  (Req 20.3); ``completed_at`` is the optional client-provided
  timestamp the service falls back to ``now`` for.
- :class:`LessonCompleteResponse` — server confirmation including the
  XP awarded for this submission. ``awarded_xp == 0`` when the request
  was a duplicate (idempotency hit), otherwise 20 (Req 11.2).
- :class:`ProgressSnapshotResponse` — Req 14.2 resume payload. Several
  fields are placeholders until later slices land (XP from Task 9.x,
  in-progress quiz/mock attempts from Tasks 11/12).
- :class:`SyncEventIn` / :class:`SyncRequest` / :class:`SyncResultOut`
  / :class:`SyncResponse` — request and response envelope for the
  ``POST /v1/progress:sync`` endpoint (Task 16.2). The wire shape
  matches design A8.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LessonCompleteRequest(BaseModel):
    """POST body for ``/v1/subtopics/{id}/lesson:complete``.

    ``client_event_id`` enables offline sync idempotency (Req 20.3) — a
    retry of the same submission produces the same persisted row, with
    ``awarded_xp=0`` on the second response.

    ``completed_at`` is optional. When omitted the service stamps the
    current server time. Clients in the offline path provide their
    locally-recorded timestamp here so the snapshot ordering reflects
    when the user finished the lesson, not when the sync replayed.
    """

    model_config = ConfigDict(extra="forbid")

    client_event_id: str | None = Field(
        default=None, max_length=64, min_length=1
    )
    completed_at: datetime | None = None


class LessonCompleteResponse(BaseModel):
    """Server confirmation for a lesson-complete submission.

    ``awarded_xp`` is the contract value — 20 on the first completion
    per (user, lesson) (Req 11.2), 0 on every duplicate. The actual XP
    ledger insert happens in Task 9.3; for now the service returns this
    contract value so clients can display "You earned 20 XP!" without
    waiting on the XP slice.
    """

    lesson_id: int
    user_id: int
    completed_at: datetime
    awarded_xp: int


class ProgressSnapshotResponse(BaseModel):
    """Resume snapshot payload (Req 14.2).

    Field-by-field provenance:

    - ``completed_lesson_ids`` — every lesson the user has finished
      (drives the "resume from where you left off" UX and the ``LessonCard``
      "completed" badge).
    - ``in_progress_quizzes`` — placeholder until the quiz slice lands
      in Task 11.x. Returned as an empty list for now so the snapshot
      shape is stable across MVP/Phase 2.
    - ``in_progress_mock_attempts`` — placeholder until Task 12.x; once
      the mock slice exists this list will surface auto-submitted
      expired attempts (Req 14.3).
    - ``cumulative_xp`` / ``level`` / ``streak`` — placeholders defaulting
      to zero until the XP slice (Task 9.x) is wired in.
    """

    completed_lesson_ids: list[int]
    in_progress_quizzes: list[dict[str, Any]] = Field(default_factory=list)
    in_progress_mock_attempts: list[dict[str, Any]] = Field(
        default_factory=list
    )
    cumulative_xp: int = 0
    level: int = 0
    streak: int = 0


# ---------------------------------------------------------------------------
# Sync schemas (Task 16.2)
# ---------------------------------------------------------------------------


class SyncEventIn(BaseModel):
    """Single inbound sync event.

    Mirrors the design A8 wire shape one-to-one. ``kind`` is kept as a
    plain ``str`` here (rather than the
    :class:`~app.features.progress.algorithms.sync_resolver.SyncEventKind`
    enum) so an unknown kind comes through the validation layer as
    "rejected by service" rather than 422 — Req 14.1 expects the
    server to dispatch what it can and tell the client which events it
    rejected, not refuse the whole batch on one bad event.

    ``payload`` is a free-form ``dict``; per-kind shape is enforced by
    :func:`~app.features.progress.algorithms.sync_resolver.validate_event_shape`
    inside the service.
    """

    model_config = ConfigDict(extra="forbid")

    client_event_id: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=32)
    client_timestamp: datetime
    payload: dict[str, Any]


class SyncRequest(BaseModel):
    """Request envelope for ``POST /v1/progress:sync``.

    Per design A8, a sync request is a list of events to ingest. The
    list is capped at 100 events per request — the PWA's Background
    Sync flow batches all pending offline events into a single
    request, but a flush window of 100 keeps a single response
    bounded; if a client has more queued, it pages.

    ``events`` is required (no default) so a missing-key body fails
    fast with a 422; an empty list is still valid and represents a
    no-op heartbeat flush.
    """

    model_config = ConfigDict(extra="forbid")

    events: list[SyncEventIn] = Field(max_length=100)


class SyncResultOut(BaseModel):
    """Per-event rejection result.

    ``reason`` mirrors the
    :class:`~app.features.progress.algorithms.sync_resolver.SyncEventResult`
    error-code set: short stable strings the client branches on rather
    than human-readable error prose. The success case carries no
    rejection rows; only ``client_event_id`` lands in the
    :attr:`SyncResponse.accepted` list.
    """

    client_event_id: str
    accepted: bool
    reason: str | None = None


class SyncResponse(BaseModel):
    """Response envelope for ``POST /v1/progress:sync``.

    Two parallel lists rather than one mixed list:

    - ``accepted`` is a flat list of ``client_event_id`` strings the
      client should remove from the IndexedDB ``pending_events`` store.
    - ``rejected`` is a list of :class:`SyncResultOut` rows with a
      ``reason`` string each so the client can branch (retry,
      re-prompt, drop) per-event.

    Splitting them mirrors the PWA's Background Sync drain step
    described in design ``Background Sync flow``: ``SW.IDB.delete(...)``
    only needs the id list, while the rejection branch needs the full
    metadata.
    """

    accepted: list[str]
    rejected: list[SyncResultOut]
