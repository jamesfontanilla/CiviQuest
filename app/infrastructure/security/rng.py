"""Cryptographic RNG wrapper.

Every randomness need in the system — OTP codes, JWT jti, quiz/mock-exam
question and option ordering, sample seeds — flows through this module. The
goal is auditability: there is exactly one place to grep when verifying that
no call site has fallen back to ``random.Random`` (which is seeded from system
time and therefore predictable).

Backed by a single shared ``secrets.SystemRandom`` instance, which is itself
a thin wrapper over the OS CSPRNG and is safe to share across threads.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from typing import Final, TypeVar

T = TypeVar("T")

_SYSRAND: Final[secrets.SystemRandom] = secrets.SystemRandom()


def randbits(k: int) -> int:
    """Return a random integer with ``k`` random bits."""
    return _SYSRAND.getrandbits(k)


def sample(population: Sequence[T], k: int) -> list[T]:
    """Return a ``k``-length list of unique elements drawn from ``population``."""
    return _SYSRAND.sample(population, k)


def shuffle(seq: list[T]) -> None:
    """Shuffle ``seq`` in place."""
    _SYSRAND.shuffle(seq)


def randbelow_six_digits() -> str:
    """Return a uniformly-random 6-digit numeric code as a zero-padded string.

    Used for OTP issuance (Requirement 2.1). The string form is preserved so
    leading zeros are not stripped on the wire. Backed by ``secrets.randbelow``
    (OS CSPRNG) rather than ``SystemRandom.randbelow`` because the latter is a
    private helper on the class.
    """
    return f"{secrets.randbelow(10**6):06d}"
