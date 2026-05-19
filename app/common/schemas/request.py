"""Reusable request schemas shared across feature routers."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    """Query-string pagination params used by every list endpoint.

    Bounds (per Requirement 15.2 and ``api-standard.md``):

    * ``skip >= 0``
    * ``1 <= limit <= 100``

    Used as a FastAPI dependency::

        def list_items(
            pagination: PaginationParams = Depends(),
            ...,
        ): ...
    """

    skip: int = Field(default=0, ge=0, description="Number of records to skip.")
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum records returned (1..100).",
    )
