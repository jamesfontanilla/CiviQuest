"""Request logging middleware: correlation ID + structured access log.

Responsibilities (in order, per request):

1. Read the inbound ``X-Request-ID`` header. Generate a fresh UUIDv4 if the
   header is absent or empty.
2. Bind the resolved request id onto ``request.state.request_id`` BEFORE
   calling the downstream ASGI app, so any code further down the stack
   (auth middleware, dependencies, services) can correlate work to it.
3. Run the request, capture the response.
4. Echo the request id back to the client via ``X-Request-ID`` on the
   response.
5. Emit one structured (JSON) access-log line on the ``app.request`` logger
   with method, path, status, and duration in milliseconds.

This middleware deliberately does not touch the request body. Bodies can be
streaming/multipart and large, and field-level redaction belongs to the audit
log service (Task 18). The :func:`redact` helper is exposed at module level so
the audit logger can reuse it.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REDACTED_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "password_hash",
        "code",
        "otp_code",
        "token",
        "authorization",
    }
)
"""Field names whose values must be replaced with :data:`_REDACTED_VALUE` on
log emission. Compared case-insensitively (lowercase the key before lookup).
"""

_REDACTED_VALUE: str = "***REDACTED***"

_logger = logging.getLogger("app.request")


def redact(value: Any) -> Any:
    """Return a deep copy of ``value`` with any redacted-key values replaced.

    Behavior:
      * ``dict`` — recurse over values; keys whose lowercase form appears in
        :data:`REDACTED_KEYS` get :data:`_REDACTED_VALUE` regardless of the
        original value's type (the value is never inspected).
      * ``list`` — recurse element-wise.
      * Anything else (scalars, ``None``) — returned as-is.

    The input is never mutated; callers may safely pass live request bodies.
    """
    if isinstance(value, dict):
        return {
            k: (
                _REDACTED_VALUE
                if isinstance(k, str) and k.lower() in REDACTED_KEYS
                else redact(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Bind a correlation id onto ``request.state`` and emit an access log."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        incoming = request.headers.get("X-Request-ID") or ""
        request_id = incoming if incoming else str(uuid.uuid4())
        request.state.request_id = request_id

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 3)

        response.headers["X-Request-ID"] = request_id
        _logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                }
            )
        )
        return response
