"""Level mapping for cumulative XP (Task 9.2, design A3).

Pure functions. The mapping is closed-form: Level N requires
``100 * N * (N + 1) / 2 = 50 * N * (N + 1)`` cumulative XP. Inverting
that yields ``N = (-1 + sqrt(1 + 4 * cumulative_xp / 50)) / 2``; we floor
to an int and apply two-step correction loops to absorb floating-point
rounding error.

Level table (sanity check):
- Level 0: 0..99 cumulative XP
- Level 1: 100..299
- Level 2: 300..599
- Level 3: 600..999
- Level 4: 1000..1499
"""

from __future__ import annotations

import math


def level_of(cumulative_xp: int) -> int:
    """Return the largest ``N`` such that ``50*N*(N+1) <= cumulative_xp``.

    Pure function. Negative inputs return 0 (the cumulative XP cache clamps
    at 0 per Req 11.7, but the math is well-defined here regardless).

    Implementation notes:

    - Short-circuits on ``cumulative_xp < 100`` so common "fresh user" calls
      avoid the ``math.sqrt`` round trip entirely.
    - The two ``while`` loops correct for floating-point rounding: ``sqrt``
      can return a slightly low or slightly high value at threshold
      boundaries. The ``-=`` loop walks back to a valid level if the
      estimate overshot; the ``+=`` loop walks forward if we undershot. In
      practice each loop runs at most once.
    """
    if cumulative_xp < 100:
        return 0

    # 50 * N * (N+1) <= cumulative_xp
    # ⇒ N <= (-1 + sqrt(1 + 4*cumulative_xp/50)) / 2
    estimate = int((-1 + math.sqrt(1 + 4 * cumulative_xp / 50)) / 2)

    # Walk down if the float estimate overshot.
    while estimate > 0 and 50 * estimate * (estimate + 1) > cumulative_xp:
        estimate -= 1
    # Walk up if the float estimate undershot.
    while 50 * (estimate + 1) * (estimate + 2) <= cumulative_xp:
        estimate += 1

    return max(0, estimate)
