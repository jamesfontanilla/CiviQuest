"""Offline-sync conflict resolver helpers (design A8, Task 16.1).

This module owns the **types** for offline-sync ingestion plus a small
:func:`validate_event_shape` helper. The actual conflict resolution
lives in :class:`app.features.progress.sync_service.SyncService`
because the dispatch is mostly orchestration (call into existing
services per ``kind``) and the conflict-resolution rule itself is
already enforced by the underlying :class:`LessonCompletion` /
:class:`XPEvent` UNIQUE on ``client_event_id``.

Why split:

- :class:`SyncEvent` and :class:`SyncEventResult` are dataclasses, not
  Pydantic models, so the resolver code does not depend on the HTTP
  layer. The router translates the inbound Pydantic
  :class:`~app.features.progress.schemas.SyncEventIn` into the
  internal dataclass before handing it to the service.
- :class:`SyncEventKind` is the closed enum the service dispatches
  on. Keeping it next to the dataclasses (rather than in
  ``schemas.py``) keeps the resolver self-contained — service code
  does not have to reach into the schema layer to switch on event
  kind.
- :func:`validate_event_shape` accepts a raw ``dict`` (the per-event
  ``payload`` plus envelope fields). It raises
  :class:`ValueError("invalid_shape")` when the dict can't be coerced
  to a :class:`SyncEvent`. The service catches that and converts it
  to a ``rejected`` result.

Per design A8 the conflict-resolution rule is:

* **Idempotent on ``client_event_id``.** When the server has already
  observed an event with this id, the persistence target's UNIQUE
  constraint short-circuits the insert and the resolver returns
  accepted-no-op.
* **Later wins on ``client_timestamp``.** Collapsed by the client's
  IndexedDB queue before the network round-trip; on the server we
  simply accept the first-seen and no-op the rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class SyncEventKind(str, Enum):
    """Closed enum of sync-event kinds (Req 14.1, 20.3).

    The string values mirror the JSON-on-the-wire kind tags. Keep
    these stable: the PWA service worker persists them in IndexedDB
    before the network round-trip, so rotating a value would
    invalidate any pending events on disk.

    Quiz-submission sync is intentionally absent: the design's
    ``prerequisite_missing`` rule needs additional handling around
    the lesson-before-quiz gate (Req 6.1) and is deferred. Quiz
    submissions only happen mid-attempt, so they never leave the
    pending-events queue without an active session anyway.
    """

    LESSON_COMPLETE = "lesson_complete"
    XP_EVENT = "xp_event"


@dataclass
class SyncEvent:
    """Internal representation of a single sync event (resolver-side).

    Constructed by the service from the inbound
    :class:`~app.features.progress.schemas.SyncEventIn` Pydantic model
    after the ``kind`` string has been resolved to a
    :class:`SyncEventKind`. Holding this as a dataclass (not a
    Pydantic model) keeps the resolver free of HTTP-shape coupling.
    """

    client_event_id: str
    kind: SyncEventKind
    client_timestamp: datetime
    payload: dict[str, Any]


@dataclass
class SyncEventResult:
    """Per-event resolution result (one entry per inbound event).

    ``reason`` is populated only when ``accepted`` is False. Reasons
    are short stable error codes the client can branch on:

    - ``invalid_shape`` — the inbound dict cannot be coerced to a
      :class:`SyncEvent` (missing/wrong-typed envelope fields, or the
      per-kind payload is malformed).
    - ``unknown_kind`` — ``kind`` is not a member of
      :class:`SyncEventKind`. Distinct from ``invalid_shape`` so the
      client can branch: an unknown kind means the server is older
      than the client, while invalid shape means the client is
      sending malformed data.
    - other strings — verbatim ``HTTPException.detail`` from the
      delegated service (e.g., ``forbidden``,
      ``invalid_xp_source``).
    """

    client_event_id: str
    accepted: bool
    reason: str | None = None


def validate_event_shape(event_dict: dict[str, Any]) -> None:
    """Raise :class:`ValueError("invalid_shape")` on a malformed dict.

    Used as the per-event validation pre-check before the service
    builds a :class:`SyncEvent` and dispatches. Pydantic enforces
    shape on the request envelope at the router boundary; this helper
    enforces the **per-kind payload** invariants Pydantic cannot
    express because ``payload`` is a free-form ``dict``.

    The check is intentionally cheap and conservative: any deviation
    from the expected shape collapses to a single ``invalid_shape``
    error code so the client has one branch to handle on the
    rejection side. Distinguishing "missing field" from "wrong type"
    would multiply the wire surface for no client benefit.

    Per-kind requirements:

    - :data:`SyncEventKind.LESSON_COMPLETE` requires an integer
      ``payload.subtopic_id``.
    - :data:`SyncEventKind.XP_EVENT` requires a string
      ``payload.source``.
    """
    if not isinstance(event_dict, dict):
        raise ValueError("invalid_shape")

    cid = event_dict.get("client_event_id")
    if not isinstance(cid, str) or not cid or len(cid) > 64:
        raise ValueError("invalid_shape")

    kind_raw = event_dict.get("kind")
    if not isinstance(kind_raw, str) or not kind_raw:
        raise ValueError("invalid_shape")

    ts = event_dict.get("client_timestamp")
    if not isinstance(ts, datetime):
        raise ValueError("invalid_shape")

    payload = event_dict.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("invalid_shape")

    # Per-kind payload shape. We coerce the kind string here only to
    # branch on the payload check; the service still does its own
    # ``SyncEventKind(kind_raw)`` conversion to surface ``unknown_kind``
    # as a distinct rejection reason.
    if kind_raw == SyncEventKind.LESSON_COMPLETE.value:
        sub = payload.get("subtopic_id")
        # ``isinstance(True, int)`` is True in Python; reject bool
        # explicitly so a JSON boolean doesn't pass as a subtopic id.
        if not isinstance(sub, int) or isinstance(sub, bool) or sub <= 0:
            raise ValueError("invalid_shape")
    elif kind_raw == SyncEventKind.XP_EVENT.value:
        source = payload.get("source")
        if not isinstance(source, str) or not source:
            raise ValueError("invalid_shape")
    # Unknown ``kind_raw`` is left to the service to surface as
    # ``unknown_kind``; we don't raise here because the envelope
    # itself is well-formed.
