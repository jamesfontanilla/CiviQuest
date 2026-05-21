"""Google ID token verification adapter.

Verifies the ``id_token`` credential returned by Google Identity Services
on the client side. Uses the ``google-auth`` library to validate the token
against Google's public keys and extract user claims (email, name, sub).

The adapter reads ``GOOGLE_CLIENT_ID`` from the environment lazily so tests
can monkeypatch without import-time side effects.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.infrastructure.external.base import ExternalServiceBase

_GOOGLE_CLIENT_ID_ENV: Final[str] = "GOOGLE_CLIENT_ID"


@dataclass(frozen=True, slots=True)
class GoogleUserInfo:
    """Verified claims extracted from a Google ID token."""

    google_id: str  # The ``sub`` claim — stable user identifier
    email: str
    name: str
    picture: str | None = None
    email_verified: bool = False


class GoogleOAuthVerifier(ExternalServiceBase):
    """Verify Google ID tokens and extract user info.

    Constructor accepts an optional ``client_id`` override for testing.
    If not provided, reads from the ``GOOGLE_CLIENT_ID`` env var at
    verification time.
    """

    def __init__(self, *, client_id: str | None = None) -> None:
        self._client_id = client_id

    def _get_client_id(self) -> str:
        """Resolve the Google Client ID, raising if not configured."""
        cid = self._client_id or os.environ.get(_GOOGLE_CLIENT_ID_ENV)
        if not cid:
            raise RuntimeError(
                f"{_GOOGLE_CLIENT_ID_ENV} environment variable is not set"
            )
        return cid

    def health_check(self) -> bool:
        """Return True if the client ID is configured."""
        try:
            self._get_client_id()
            return True
        except RuntimeError:
            return False

    def verify_token(self, token: str) -> GoogleUserInfo:
        """Verify a Google ID token and return extracted user info.

        Raises:
            ValueError: If the token is invalid, expired, or not issued
                for our client ID.
        """
        client_id = self._get_client_id()
        try:
            id_info = google_id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                client_id,
            )
        except Exception as exc:
            raise ValueError(f"Invalid Google ID token: {exc}") from exc

        # Ensure the token was issued by Google accounts
        issuer = id_info.get("iss", "")
        if issuer not in ("accounts.google.com", "https://accounts.google.com"):
            raise ValueError(f"Invalid token issuer: {issuer}")

        return GoogleUserInfo(
            google_id=id_info["sub"],
            email=id_info.get("email", ""),
            name=id_info.get("name", ""),
            picture=id_info.get("picture"),
            email_verified=id_info.get("email_verified", False),
        )
