"""Permissive bearer-token decoder middleware.

This middleware never rejects a request. It only attempts to surface the
decoded JWT claims onto ``request.state`` so that downstream FastAPI
dependencies (notably ``get_current_user`` in Task 5.1) can decide whether
``401`` or ``403`` applies.

Why permissive: the auth-vs-no-auth distinction is policy that varies per
route (``/health`` is public, ``/v1/...`` is mostly authenticated, the password
reset endpoint is anonymous). Mounting the policy in a middleware would
duplicate the dependency logic and make per-route overrides awkward. Keeping
the middleware purely informational lets the dependency layer own the policy.

State contract written to ``request.state``:

* ``request.state.token_claims`` — ``dict`` of decoded JWT claims, or ``None``.
* ``request.state.user`` — always set to ``None`` here. The actual ``User``
  load happens in the ``get_current_user`` dependency, which has access to a
  DB session.
"""

from __future__ import annotations

import jwt
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.infrastructure.security.jwt import decode_token


class AuthMiddleware(BaseHTTPMiddleware):
    """Decode a bearer token if present; never raise."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        claims: dict[str, object] | None = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            if token:
                try:
                    claims = decode_token(token)
                except (
                    jwt.ExpiredSignatureError,
                    jwt.InvalidTokenError,
                    RuntimeError,
                ):
                    # Expired, tampered, malformed, or missing JWT_SECRET:
                    # treat as anonymous and let the dependency layer decide.
                    claims = None

        request.state.token_claims = claims
        request.state.user = None
        return await call_next(request)
