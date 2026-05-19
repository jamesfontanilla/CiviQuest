"""HS256 session-token encoding and decoding.

The signing secret is read lazily from the ``JWT_SECRET`` environment variable
on every encode/decode. Reading it lazily (rather than at module import) lets
tests use ``monkeypatch.setenv`` and lets the deploy environment populate the
secret after the process starts.

Callers are responsible for translating ``pyjwt`` exceptions
(``ExpiredSignatureError``, ``InvalidSignatureError``, ``InvalidTokenError``,
etc.) into HTTP 401 responses. We deliberately do not wrap them in custom
exceptions: the ``pyjwt`` hierarchy is the one downstream code already knows.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Final

import jwt

JWT_ALGORITHM: Final[str] = "HS256"
JWT_TTL_HOURS: Final[int] = 24
_JWT_SECRET_ENV: Final[str] = "JWT_SECRET"


def _secret() -> str:
    secret = os.environ.get(_JWT_SECRET_ENV)
    if not secret:
        # Fallback for demo/free-tier deploys where env vars aren't set.
        # In production, always set JWT_SECRET to a unique random value.
        secret = "civiquest-demo-secret-change-me-in-production-32b"
    return secret


def encode_token(*, sub: str | int, jti: str | None = None) -> tuple[str, dict[str, Any]]:
    """Mint a fresh JWT for the given subject.

    Returns:
        ``(token, claims)`` where ``claims`` is the dict that was signed, so
        callers (e.g., the auth service persisting a session row) can record
        ``jti`` / ``iat`` / ``exp`` without a redundant decode.
    """
    now = datetime.now(tz=timezone.utc)
    iat = int(now.timestamp())
    exp = iat + JWT_TTL_HOURS * 3600
    claims: dict[str, Any] = {
        "sub": str(sub),
        "jti": jti if jti is not None else str(uuid.uuid4()),
        "iat": iat,
        "exp": exp,
    }
    token = jwt.encode(claims, _secret(), algorithm=JWT_ALGORITHM)
    return token, claims


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify ``token``.

    Lets ``pyjwt`` raise its own exceptions on failure: ``ExpiredSignatureError``
    on stale tokens, ``InvalidSignatureError`` on tampered signatures, and the
    broader ``InvalidTokenError`` family on structural problems.
    """
    return jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
