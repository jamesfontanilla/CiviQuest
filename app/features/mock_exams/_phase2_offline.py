"""Phase 2 mock-exam offline-blocking surface — documentation only.

This file is intentionally empty of executable code. It exists to
keep the spec's Task 13.2 (offline blocking for the mock-exam start
endpoint) discoverable from the slice it belongs to, while making
clear that the behavior does not live here.

Where the offline-blocking actually lives
-----------------------------------------

Per design Req 20.4 ("Offline behavior — Mock exams MUST NOT be
startable while offline"), the block is **client-side only**:

- The PWA service worker (``web/src/service-worker.ts``, Task 20.3)
  intercepts ``POST /v1/mock-exams/attempts``. When ``navigator.onLine``
  is ``false``, the worker returns a synthetic
  ``409 mock_exam_offline_unavailable`` response without forwarding to
  the network.
- The "Start Mock" UI button is hidden / disabled while
  ``navigator.onLine`` is ``false`` so the learner does not even see
  the entry point.

Why the server is **not** the right place for this
--------------------------------------------------

The server cannot meaningfully tell whether a request originated from
an online or offline client. By the time a request reaches the server
the client is necessarily online (network round-trip succeeded). The
only authoritative place to enforce "the user's device is offline" is
the device itself. Adding a server-side gate would be either redundant
(against an online client) or unenforceable (against an offline one).

Server-side guarantees that **do** apply
----------------------------------------

The server keeps responsibility for the in-progress invariants that
matter once an attempt exists:

- Req 10.8 / Property 36 — at most one IN_PROGRESS attempt per user
  (partial unique index on
  :class:`~app.features.mock_exams.models.MockExamAttempt`).
- Req 19.3 / Property 30 — server-authoritative timer: on remaining==0
  the next request transitions to ``AUTO_SUBMITTED`` BEFORE any other
  side effect.
- Req 19.1 / Property 29 — every other read/write surface returns
  ``409 exam_in_progress`` while a mock is IN_PROGRESS.

Those guarantees are independent of the client's online state and
remain enforced regardless of how the offline-block is implemented in
the PWA.

When this file goes away
------------------------

Once Task 20.3 lands, the corresponding service-worker code becomes
the canonical home for the offline-block logic. This stub can be
deleted at that point; it exists only so the spec's task tree
remains traceable while the PWA work is queued.
"""

from __future__ import annotations
