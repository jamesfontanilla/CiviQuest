"""Global exception handlers that produce the canonical ``ErrorResponse`` envelope.

Two handlers live here:

* :func:`generic_500_handler` — catches every unhandled :class:`Exception` and
  returns a fixed ``500`` body. The original exception is logged server-side
  (with traceback) but never echoed to the client. This is the
  information-leakage barrier called out in ``security-policy.md`` § Error
  Handling.
* :func:`http_exception_handler` — translates :class:`fastapi.HTTPException`
  raised by services and dependencies into the same envelope shape, preserving
  the original ``status_code`` and using the detail string verbatim as the
  client-facing ``message``.

Both handlers are registered through :func:`register_exception_handlers` so
``main.py`` only has to make a single call.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.common.schemas.response import ErrorDetail, ErrorResponse

_logger = logging.getLogger(__name__)


async def generic_500_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a generic ``500`` response without leaking exception internals.

    The full exception (including traceback) is logged via ``logger.exception``
    so operators can still triage the failure; the client only sees the canned
    ``Internal Server Error`` message.
    """
    _logger.exception(
        "unhandled_exception",
        extra={"request_id": getattr(request.state, "request_id", None)},
    )
    body = ErrorResponse(
        error=ErrorDetail(message="Internal Server Error", code="INTERNAL_ERROR")
    )
    return JSONResponse(status_code=500, content=body.model_dump())


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Convert :class:`HTTPException` into the canonical envelope.

    The error ``code`` is derived as ``HTTP_<status_code>`` (e.g. ``HTTP_404``).
    The ``message`` is the exception's ``detail`` — services are expected to
    pass user-safe strings per ``api-standard.md``.
    """
    body = ErrorResponse(
        error=ErrorDetail(
            message=str(exc.detail),
            code=f"HTTP_{exc.status_code}",
        )
    )
    return JSONResponse(status_code=exc.status_code, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    """Register both handlers against ``app``.

    Called from ``app/main.py`` so the wiring lives in one place.
    """
    app.add_exception_handler(Exception, generic_500_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
