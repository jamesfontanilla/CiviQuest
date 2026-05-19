"""FastAPI application entrypoint.

This module exposes the ``app`` object that ``uvicorn app.main:app`` resolves
to. It wires middlewares, exception handlers, and all feature routers.

Middleware add-order matters: Starlette processes middlewares in reverse-add
order (last-added runs first). We add logging first, then auth, so the
request flow is: logging → auth → route handler.

Setting ``DISABLE_SCHEDULER=1`` in the environment makes ``start_scheduler``
a no-op; the test suite sets this in ``conftest.py`` so timers do not run
during unit tests.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.common.middlewares.auth import AuthMiddleware
from app.common.middlewares.error_handler import register_exception_handlers
from app.common.middlewares.logging import RequestLoggingMiddleware
from app.features.achievements.router import router as achievement_router
from app.features.admin.router import router as admin_router
from app.features.audit.router import router as audit_router
from app.features.mastery.router import router as mastery_router
from app.features.auth.router import router as auth_router
from app.features.content.router import router as content_router
from app.features.gamification.router import router as gamification_router
from app.features.tutor.router import router as tutor_router
from app.features.focus.router import router as focus_router
from app.features.planner.router import router as planner_router
from app.features.leaderboards.router import router as leaderboard_router
from app.features.mock_exams.router import router as mock_exam_router
from app.features.otp.router import router as otp_router
from app.features.progress.router import router as progress_router
from app.features.quizzes.router import router as quiz_router
from app.features.xp.router import router as xp_router
from app.infrastructure.scheduler.jobs import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the scheduler on app boot, auto-seed if DB is empty."""
    del app  # unused; the lifespan signature requires the parameter

    # Ensure tables exist and seed if empty (handles ephemeral deploys
    # like Render free tier where the SQLite file is wiped on restart).
    from app.infrastructure.database.base import Base
    from app.infrastructure.database.session import SessionLocal, engine

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        from app.features.users.models import User

        admin_exists = session.query(User).filter(
            User.email == "admin@cse.local"
        ).first()
        if admin_exists is None:
            from scripts.seed import seed_database

            seed_database(session)
    except Exception:
        pass  # Non-fatal: app still boots even if seed fails
    finally:
        session.close()

    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(lifespan=lifespan)

# --- CORS ------------------------------------------------------------------
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten to your Vercel domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Middlewares -----------------------------------------------------------
# Add order: logging first, auth second. Starlette processes in reverse-add
# order, so the actual request flow is: RequestLoggingMiddleware (sets
# request_id) → AuthMiddleware (decodes bearer) → route handler.
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(AuthMiddleware)

# --- Exception handlers ----------------------------------------------------
register_exception_handlers(app)

# --- Feature routers -------------------------------------------------------
# Each router already carries its own prefix (e.g. /v1/auth, /v1, /v1/admin).
app.include_router(auth_router)
app.include_router(otp_router)
app.include_router(content_router)
app.include_router(progress_router)
app.include_router(xp_router)
app.include_router(quiz_router)
app.include_router(mock_exam_router)
app.include_router(leaderboard_router)
app.include_router(achievement_router)
app.include_router(admin_router)
app.include_router(audit_router)
app.include_router(mastery_router)
app.include_router(gamification_router)
app.include_router(tutor_router)
app.include_router(planner_router)
app.include_router(focus_router)


# --- Health probe ----------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    """Unauthenticated health probe per ``api-standard.md``."""
    return {"status": "ok"}
