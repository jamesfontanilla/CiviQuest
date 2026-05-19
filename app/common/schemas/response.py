"""Reusable response schemas shared across feature routers.

This module defines the canonical envelopes used by every list endpoint
(``PaginatedResponse``) and every error response (``ErrorResponse``) per
``api-standard.md``.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard envelope for paginated list endpoints.

    Shape per ``api-standard.md``::

        {
            "items": [...],
            "total": 100,
            "skip": 0,
            "limit": 20,
        }

    Routers wire this via ``response_model=PaginatedResponse[ItemResponse]``.
    """

    items: list[T]
    total: int
    skip: int
    limit: int


class ErrorDetail(BaseModel):
    """The ``error`` body of an :class:`ErrorResponse`."""

    message: str
    code: str


class ErrorResponse(BaseModel):
    """Canonical error envelope per ``api-standard.md``::

        {
            "error": {
                "message": "Item not found",
                "code": "NOT_FOUND",
            }
        }

    All non-2xx responses produced by the global error handler use this shape.
    """

    error: ErrorDetail
