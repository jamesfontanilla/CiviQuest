"""Server-authoritative mock-exam timer (Task 12.4, Req 10.3, 14.3, 19.3).

Two pure helpers — ``remaining_seconds`` and ``is_expired`` — that the
service layer calls on every read or write of an attempt. The timer
authority lives here, not on the client; the client only displays
what the server reports (Property 30).

Naive datetime safety
---------------------
The ``started_at`` stamp can come from SQLite which strips tzinfo on
some round-trips (the ``DateTime(timezone=True)`` column is honoured
by the engine but the underlying SQLite TEXT is naive UTC ISO).
``remaining_seconds`` defends against that by upgrading naive inputs
to UTC. The service always passes a UTC-aware ``now``, so the
arithmetic is well-defined as long as the caller hasn't manufactured
a half-naive timeline by hand.

Why integer-floor on ``remaining``
-----------------------------------
``remaining = time_limit_minutes * 60 - int(elapsed)``. Truncating
``elapsed`` is the right boundary behaviour: at exactly ``time_limit``,
``remaining`` is ``0`` (expired). The Property 30 test against the
boundary case relies on this — flipping to a half-second-rounded
value would let a mock attempt linger one tick past the threshold.
"""

from __future__ import annotations

from datetime import datetime, timezone


def remaining_seconds(
    *,
    started_at: datetime,
    time_limit_minutes: int,
    now: datetime,
) -> int:
    """Return ``max(0, time_limit*60 - elapsed)`` as a non-negative int.

    Args:
        started_at: When the attempt began (Req 10.3 anchor). Naive
            datetimes are assumed UTC for safety.
        time_limit_minutes: The attempt's snapshotted limit at start
            (Req 19.3 — comes from the attempt row, not the live
            config).
        now: Caller-supplied UTC-aware "now" so tests can pin the
            clock without monkeypatching.

    Returns:
        Remaining seconds, floored at zero. The integer floor lets
        the boundary case (``elapsed == time_limit``) report exactly
        ``0`` rather than a near-zero positive.
    """
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    elapsed = (now - started_at).total_seconds()
    return max(0, time_limit_minutes * 60 - int(elapsed))


def is_expired(
    *,
    started_at: datetime,
    time_limit_minutes: int,
    now: datetime,
) -> bool:
    """Return True iff :func:`remaining_seconds` is zero.

    Pure convenience over the above; defined as a separate function so
    the service-side branch reads naturally
    (``if is_expired(...): auto_submit()`` instead of ``if
    remaining_seconds(...) == 0:``).
    """
    return (
        remaining_seconds(
            started_at=started_at,
            time_limit_minutes=time_limit_minutes,
            now=now,
        )
        == 0
    )
