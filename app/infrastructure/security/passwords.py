"""bcrypt-based password hashing.

Wraps ``bcrypt`` so the rest of the codebase never touches raw byte / string
encoding details and so the work factor is configured in exactly one place.

Security notes:
- ``BCRYPT_ROUNDS`` is set to 12, which exceeds the >= 10 floor required by
  Requirement 1.6. Twelve is the modern default; tune downward only if
  benchmarks on the deployment hardware demand it.
- bcrypt silently truncates inputs longer than 72 bytes. We refuse those
  inputs explicitly with a ``ValueError`` rather than truncating, which would
  create non-obvious password collisions for long passphrases. Callers are
  expected to validate length at the schema layer; this is a defense in depth.
"""

from __future__ import annotations

from typing import Final

import bcrypt

BCRYPT_ROUNDS: Final[int] = 12
_MAX_PASSWORD_BYTES: Final[int] = 72


def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash of ``plaintext``.

    Raises:
        ValueError: ``plaintext`` exceeds the 72-byte bcrypt input limit.
    """
    encoded = plaintext.encode("utf-8")
    if len(encoded) > _MAX_PASSWORD_BYTES:
        raise ValueError(
            f"password exceeds bcrypt's {_MAX_PASSWORD_BYTES}-byte input limit"
        )
    salted = bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=BCRYPT_ROUNDS))
    return salted.decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return True iff ``plaintext`` matches the bcrypt-encoded ``hashed``.

    Returns False on any malformed hash or length-overflowing plaintext rather
    than raising, so callers do not need to distinguish "wrong password" from
    "garbled stored hash" at the call site.
    """
    encoded = plaintext.encode("utf-8")
    if len(encoded) > _MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed.encode("utf-8"))
    except ValueError:
        # bcrypt raises ValueError on malformed hashes (wrong prefix, bad length).
        return False
