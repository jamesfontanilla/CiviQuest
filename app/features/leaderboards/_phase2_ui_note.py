"""Phase 2 leaderboard UI surface — documentation only.

This file is intentionally empty of executable code. It exists to
keep the spec's Task 14.6 ("Promote weekly/monthly leaderboards to
default UI surfaces") discoverable from the slice it belongs to,
while making clear that the work does not live here.

Where the Phase 2 UI work actually lives
----------------------------------------

Per design (Req 12.2, 12.3) and Task 21.5 ("Leaderboard, Profile/XP,
Admin dashboard"), the three-tab leaderboard surface is purely a
PWA UI concern:

- The PWA's leaderboard page renders three tabs — global / weekly /
  monthly — and calls the corresponding backend endpoint per tab:
  ``GET /v1/leaderboards/global``, ``GET /v1/leaderboards/weekly``,
  ``GET /v1/leaderboards/monthly``.
- All three endpoints are already shipped as part of MVP (Task 14.4
  / Req 12.1, 12.2, 12.3); the backend exposes the weekly + monthly
  views even though the MVP UI only exposes the global tab.

What the backend already provides
---------------------------------

- :func:`app.features.leaderboards.router.get_global_leaderboard`
- :func:`app.features.leaderboards.router.get_weekly_leaderboard`
- :func:`app.features.leaderboards.router.get_monthly_leaderboard`

All three return ``list[LeaderboardEntry]`` with the spec shape from
Req 12.5 (``user_id``, ``display_name``, ``level``, ``xp_window``,
``category``). Window math for weekly / monthly is computed
server-side from the design A5 bounds, so the PWA never needs to
know about ISO weeks or calendar months — it just hits the route.

Why no server work is needed for Task 14.6
------------------------------------------

The MVP backend already exposes everything the Phase 2 UI requires.
Task 14.6 is a pure UI re-arrangement:

- "Promote" means change the default tab on the leaderboard page so
  weekly / monthly are first-class instead of secondary.
- The Phase 2 Service Worker treats ``/v1/leaderboards/*`` as
  network-only (per design's "State GETs" rule, Task 20.3), so no
  caching plumbing is needed either.

This stub can be deleted once Task 21.5 lands and the PWA has the
three tabs visible by default.
"""

from __future__ import annotations
