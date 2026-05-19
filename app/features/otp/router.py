"""FastAPI router placeholder for the OTP feature.

For MVP, every user-facing OTP flow is invoked through the auth router
(``POST /v1/auth/email-verifications``, ``POST /v1/auth/password-resets``,
etc.), so this module only exposes an empty ``APIRouter`` with the canonical
``/v1/otp`` prefix. Mounting it from ``main.py`` is a no-op, which keeps the
include-router wiring uniform across slices and gives Phase 2 a stable
landing surface for any internal-only OTP helpers without a follow-up
import-path change.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/v1/otp", tags=["otp"])
