"""Offline-sync ingestion service (Task 16.2).

``POST /v1/progress:sync`` lands here. The service iterates over the
inbound event list, validates and dispatches each event to the
appropriate existing service
(:meth:`ProgressService.complete_lesson` or :meth:`XPService.award`),
and returns a partition of accepted-id list and rejected-result
list.

Why a dedicated service rather than a method on
:class:`ProgressService`:

- The dispatch logic is cross-feature (progress + xp). Putting it on
  ``ProgressService`` would drag the XP service into a slice that
  otherwise stops at lesson-completion.
- The error-handling shape is different. The other progress
  endpoints raise :class:`HTTPException` and let the global error
  handler turn it into a 4xx body; this endpoint converts a
  per-event exception into a ``rejected`` row and keeps draining the
  rest of the batch (Req 14.1 expects the server to tell the client
  which events it rejected, not refuse the whole batch on one bad
  event).

The service does NOT own the mock-exam guard
(:func:`app.common.deps.require_no_active_mock`). Sync should keep
working mid-mock — a learner who started a mock attempt may still
be flushing pre-mock pending events from the offline queue.
Blocking sync would leave those events permanently stuck in
IndexedDB.

Resolution rule (Property 32):

1. Validate the inbound dict via :func:`validate_event_shape` →
   ``rejected`` with ``reason='invalid_shape'`` on failure.
2. Resolve ``kind`` to :class:`SyncEventKind` → ``rejected`` with
   ``reason='unknown_kind'`` on a kind the server doesn't accept.
3. Idempotency early-exit: look up the persistence target by
   ``client_event_id``; if a row exists, return accepted-no-op.
   "Later wins on ``client_timestamp`` collision" is collapsed by
   client-side dedup before sync, so on the server we just accept
   the first-seen and no-op the rest. (We do not rewrite history
   even when the prior row is older — the design's later-wins
   guarantee is realised end-to-end through the IndexedDB queue.)
4. Dispatch by ``kind`` to the right service. Both downstream
   services are themselves idempotent on ``client_event_id``, so the
   step-3 short-circuit is an optimisation, not a correctness
   requirement.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from app.features.content.repository import (
    LessonRepository,
    SubtopicRepository,
)
from app.features.progress.algorithms.sync_resolver import (
    SyncEvent,
    SyncEventKind,
    SyncEventResult,
    validate_event_shape,
)
from app.features.progress.repository import ProgressRepository
from app.features.progress.schemas import (
    LessonCompleteRequest,
    SyncEventIn,
)
from app.features.progress.service import ProgressService
from app.features.users.models import User
from app.features.xp.models import XPSource
from app.features.xp.repository import XPRepository
from app.features.xp.service import XPService


class SyncService:
    """Drain an offline-sync batch by dispatching each event.

    Constructor takes both the high-level services
    (:class:`ProgressService`, :class:`XPService`) and the
    persistence-layer repositories
    (:class:`ProgressRepository`, :class:`XPRepository`,
    :class:`SubtopicRepository`, :class:`LessonRepository`). The
    repos exist so the early-exit idempotency lookup
    (``get_by_client_event_id`` / ``get_event_by_client_event_id``)
    can be performed without re-running the full service path. The
    services are still the dispatch targets for fresh (non-replay)
    events.

    The subtopic / lesson repos are wired in for future
    payload-validation use — e.g., resolving a ``subtopic_id`` to a
    lesson before delegating — but the current MVP delegates that
    resolution to :meth:`ProgressService.complete_lesson` directly.
    Holding the repos at construction keeps the slice's dependency
    surface stable across Phase 2 work.
    """

    def __init__(
        self,
        *,
        progress_service: ProgressService,
        progress_repo: ProgressRepository,
        xp_repo: XPRepository,
        xp_service: XPService,
        subtopic_repo: SubtopicRepository,
        lesson_repo: LessonRepository,
    ) -> None:
        self._progress_service = progress_service
        self._progress_repo = progress_repo
        self._xp_repo = xp_repo
        self._xp_service = xp_service
        self._subtopic_repo = subtopic_repo
        self._lesson_repo = lesson_repo

    # ------------------------------------------------------------------
    # sync_events
    # ------------------------------------------------------------------

    def sync_events(
        self, *, user: User, events: list[SyncEventIn]
    ) -> tuple[list[str], list[SyncEventResult]]:
        """Process every event in ``events`` and return the partition.

        Returns:
            ``(accepted_ids, rejected_results)``.

            - ``accepted_ids`` is a flat list of ``client_event_id``
              strings the client should remove from its IndexedDB
              ``pending_events`` store.
            - ``rejected_results`` is a list of
              :class:`SyncEventResult` rows with a ``reason`` string
              each so the client can branch (retry, re-prompt, drop)
              per-event.

        Per Req 14.1 + 20.3 + Property 32, a re-submission of the
        same accepted set produces no further state change: every
        accepted event is accepted again on replay, and the row count
        of the underlying tables does not change between the first
        and second drain.
        """
        accepted: list[str] = []
        rejected: list[SyncEventResult] = []

        for inbound in events:
            result = self._process_one(user=user, event=inbound)
            if result.accepted:
                accepted.append(result.client_event_id)
            else:
                rejected.append(result)

        return accepted, rejected

    # ------------------------------------------------------------------
    # _process_one
    # ------------------------------------------------------------------

    def _process_one(
        self, *, user: User, event: SyncEventIn
    ) -> SyncEventResult:
        """Validate, idempotency-check, and dispatch a single event.

        Order:

        1. Build a raw ``dict`` view of the event and run
           :func:`validate_event_shape`. Any :class:`ValueError`
           raised collapses to a ``rejected`` result with
           ``reason='invalid_shape'``.
        2. Resolve ``kind`` to :class:`SyncEventKind`. An unknown
           ``kind`` value is a distinct rejection reason
           (``unknown_kind``) — the server is older than the client.
        3. Idempotency early-exit: look up the persistence target's
           row by ``client_event_id``. When a prior row exists, the
           event is acknowledged as accepted-no-op without dispatch.
           This is an optimisation: the underlying services would
           also short-circuit, but the early-exit keeps the
           per-event cost at one indexed lookup on replay.
        4. Dispatch to the right handler. :class:`HTTPException`
           bubbled up from the handler is converted into a rejection
           carrying the exception's ``detail``. :class:`ValueError`
           (raised inside Pydantic-coerce paths or the handler's own
           validation) collapses to its ``str(e)`` reason.
        """
        # Build a dict view for validate_event_shape and dispatch.
        # Pydantic v2 carries a coerced datetime on
        # ``inbound.client_timestamp`` which validate_event_shape
        # accepts as-is.
        event_dict = {
            "client_event_id": event.client_event_id,
            "kind": event.kind,
            "client_timestamp": event.client_timestamp,
            "payload": event.payload,
        }

        # 1. Per-event shape validation.
        try:
            validate_event_shape(event_dict)
        except ValueError as exc:
            return SyncEventResult(
                client_event_id=event.client_event_id,
                accepted=False,
                reason=str(exc) or "invalid_shape",
            )

        # 2. Resolve kind. Distinct ``unknown_kind`` reason so the
        # client can branch (retry vs. drop).
        try:
            kind = SyncEventKind(event.kind)
        except ValueError:
            return SyncEventResult(
                client_event_id=event.client_event_id,
                accepted=False,
                reason="unknown_kind",
            )

        sync_event = SyncEvent(
            client_event_id=event.client_event_id,
            kind=kind,
            client_timestamp=_to_utc(event.client_timestamp),
            payload=event.payload,
        )

        # 3. Idempotency early-exit. We don't rewrite history even
        # when the prior row is older — the row exists, so we accept
        # the replay as a no-op. (Property 32: replaying an accepted
        # set produces no further state change.)
        if self._already_persisted(sync_event):
            return SyncEventResult(
                client_event_id=event.client_event_id, accepted=True
            )

        # 4. Dispatch.
        try:
            if kind == SyncEventKind.LESSON_COMPLETE:
                return self._dispatch_lesson_complete(user, sync_event)
            if kind == SyncEventKind.XP_EVENT:
                return self._dispatch_xp_event(user, sync_event)
        except HTTPException as exc:
            return SyncEventResult(
                client_event_id=event.client_event_id,
                accepted=False,
                reason=(
                    str(exc.detail) if exc.detail else "forbidden"
                ),
            )
        except ValueError as exc:
            return SyncEventResult(
                client_event_id=event.client_event_id,
                accepted=False,
                reason=str(exc) or "invalid_shape",
            )

        # Unreachable: every SyncEventKind member is handled above.
        return SyncEventResult(  # pragma: no cover - defensive guard
            client_event_id=event.client_event_id,
            accepted=False,
            reason="unknown_kind",
        )

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    def _already_persisted(self, event: SyncEvent) -> bool:
        """Return True iff a prior row with this id already exists.

        Routes the lookup to the right repository per ``kind``:

        - :data:`SyncEventKind.LESSON_COMPLETE` →
          :meth:`ProgressRepository.get_by_client_event_id`.
        - :data:`SyncEventKind.XP_EVENT` →
          :meth:`XPRepository.get_event_by_client_event_id`.

        The downstream services are themselves idempotent on
        ``client_event_id``, but doing the lookup here keeps the
        per-event cost at one indexed lookup on replay rather than
        the full ``complete_lesson`` / ``award`` codepath.
        """
        if event.kind == SyncEventKind.LESSON_COMPLETE:
            prior = self._progress_repo.get_by_client_event_id(
                event.client_event_id
            )
            return prior is not None
        if event.kind == SyncEventKind.XP_EVENT:
            prior = self._xp_repo.get_event_by_client_event_id(
                event.client_event_id
            )
            return prior is not None
        return False  # pragma: no cover - defensive guard

    # ------------------------------------------------------------------
    # Per-kind handlers
    # ------------------------------------------------------------------

    def _dispatch_lesson_complete(
        self, user: User, event: SyncEvent
    ) -> SyncEventResult:
        """Delegate to :meth:`ProgressService.complete_lesson`.

        ``ProgressService`` already handles offline-sync idempotency
        on ``client_event_id`` and on the ``(user, lesson)`` UNIQUE,
        so the early-exit lookup in :meth:`_already_persisted` is
        redundant but cheap. We re-use the service's full codepath
        for fresh events so the XP fan-out and the same response
        shape are exercised.

        Per the prompt's payload contract, the expected payload shape
        is ``{"subtopic_id": int, "completed_at": datetime | None}``.
        ``completed_at`` defaults to the event's
        ``client_timestamp`` when absent so the persisted row's
        timestamp reflects when the user finished the lesson, not
        when the sync replayed.
        """
        subtopic_id = event.payload["subtopic_id"]
        completed_at_raw = event.payload.get("completed_at")
        completed_at = (
            _coerce_datetime(completed_at_raw)
            if completed_at_raw is not None
            else event.client_timestamp
        )
        payload = LessonCompleteRequest(
            client_event_id=event.client_event_id,
            completed_at=completed_at,
        )
        self._progress_service.complete_lesson(
            user=user, subtopic_id=int(subtopic_id), payload=payload
        )
        return SyncEventResult(
            client_event_id=event.client_event_id, accepted=True
        )

    def _dispatch_xp_event(
        self, user: User, event: SyncEvent
    ) -> SyncEventResult:
        """Delegate to :meth:`XPService.award`.

        Per the prompt's payload contract, the expected payload shape
        is ``{"source": str, "amount": int, "source_ref_id": int |
        None}``. ``source`` is parsed as the closed
        :class:`XPSource` enum (Req 11.1); an unknown value rejects
        as ``invalid_shape``. The XPService enforces the
        non-negative-amount rule (Req 11.7) on its own and surfaces
        violations as :class:`HTTPException`, which the outer
        ``except`` catches.
        """
        try:
            source = XPSource(event.payload["source"])
        except (KeyError, ValueError):
            return SyncEventResult(
                client_event_id=event.client_event_id,
                accepted=False,
                reason="invalid_shape",
            )

        amount = event.payload.get("amount")
        if amount is not None and (
            not isinstance(amount, int) or isinstance(amount, bool)
        ):
            return SyncEventResult(
                client_event_id=event.client_event_id,
                accepted=False,
                reason="invalid_shape",
            )

        source_ref_id = event.payload.get("source_ref_id")
        if source_ref_id is not None and (
            not isinstance(source_ref_id, int)
            or isinstance(source_ref_id, bool)
        ):
            return SyncEventResult(
                client_event_id=event.client_event_id,
                accepted=False,
                reason="invalid_shape",
            )

        self._xp_service.award(
            user=user,
            source=source,
            amount=amount,
            occurred_at=event.client_timestamp,
            source_ref_id=source_ref_id,
            client_event_id=event.client_event_id,
        )
        return SyncEventResult(
            client_event_id=event.client_event_id, accepted=True
        )


def _to_utc(when: datetime) -> datetime:
    """Coerce a Pydantic-deserialised datetime to aware UTC.

    The wire format is ISO 8601 with a ``Z`` (or explicit offset)
    suffix; Pydantic v2 returns those as aware datetimes. A naive
    datetime falls through here as UTC because the server-side
    "later-wins" comparison must compare apples-to-apples — a naive
    datetime would be unorderable against an aware one and would
    raise during the ``ProgressService`` codepath.
    """
    if when.tzinfo is None:
        return when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def _coerce_datetime(value: object) -> datetime:
    """Coerce a payload-side ``completed_at`` to aware UTC.

    The payload is a free-form ``dict``, so the value may arrive as
    an ISO string (the JSON wire format) or as an already-coerced
    :class:`datetime` (e.g., when the caller built the event
    in-process). Either way we want an aware UTC datetime; anything
    else raises and the outer ``except ValueError`` collapses to
    ``invalid_shape``.
    """
    if isinstance(value, datetime):
        return _to_utc(value)
    if isinstance(value, str):
        # ``datetime.fromisoformat`` accepts ``Z`` from Python 3.11+;
        # the project pins 3.12 in pyproject so this is safe.
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:  # pragma: no cover - re-raised
            raise ValueError("invalid_shape") from exc
        return _to_utc(parsed)
    raise ValueError("invalid_shape")
