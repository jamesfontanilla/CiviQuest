"""Unit tests for the shared request/response schemas.

These cover :class:`PaginationParams` bounds (Requirement 15.2) and the
canonical paginated/error envelopes from ``api-standard.md``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.common.schemas.request import PaginationParams
from app.common.schemas.response import (
    ErrorDetail,
    ErrorResponse,
    PaginatedResponse,
)


# ---------------------------------------------------------------------------
# PaginationParams
# ---------------------------------------------------------------------------


def test_pagination_params_defaults() -> None:
    """Defaults match the documented contract: ``skip=0, limit=20``."""
    params = PaginationParams()
    assert params.skip == 0
    assert params.limit == 20


def test_pagination_params_accepts_bounds() -> None:
    """Both inclusive limit bounds (1 and 100) validate."""
    lower = PaginationParams(skip=0, limit=1)
    upper = PaginationParams(skip=0, limit=100)
    assert lower.limit == 1
    assert upper.limit == 100


def test_pagination_params_rejects_negative_skip() -> None:
    """``skip < 0`` violates the ``ge=0`` constraint."""
    with pytest.raises(ValidationError):
        PaginationParams(skip=-1)


def test_pagination_params_rejects_zero_limit() -> None:
    """``limit == 0`` violates the ``ge=1`` constraint."""
    with pytest.raises(ValidationError):
        PaginationParams(limit=0)


def test_pagination_params_rejects_oversized_limit() -> None:
    """``limit > 100`` violates the ``le=100`` constraint."""
    with pytest.raises(ValidationError):
        PaginationParams(limit=101)


# ---------------------------------------------------------------------------
# PaginatedResponse[T]
# ---------------------------------------------------------------------------


def test_paginated_response_holds_typed_items() -> None:
    """``PaginatedResponse[T]`` parametrizes ``items`` and round-trips via dump."""
    response = PaginatedResponse[str](
        items=["a", "b"], total=2, skip=0, limit=2
    )
    assert response.items == ["a", "b"]
    assert response.model_dump() == {
        "items": ["a", "b"],
        "total": 2,
        "skip": 0,
        "limit": 2,
    }


# ---------------------------------------------------------------------------
# ErrorResponse / ErrorDetail
# ---------------------------------------------------------------------------


def test_error_response_shape() -> None:
    """``ErrorResponse`` serializes to the exact envelope from api-standard.md."""
    response = ErrorResponse(
        error=ErrorDetail(message="not found", code="NOT_FOUND")
    )
    assert response.model_dump() == {
        "error": {"message": "not found", "code": "NOT_FOUND"}
    }
