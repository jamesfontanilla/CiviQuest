"""SQLAlchemy engine, session factory, and FastAPI ``get_db`` dependency.

Supports both SQLite (local dev / tests) and PostgreSQL (production via
Supabase). The dialect is inferred from DATABASE_URL:

- ``sqlite:///*``  → SQLite with WAL pragmas, check_same_thread=False
- ``postgresql://*`` or ``postgresql+psycopg2://*`` → Postgres with a
  connection pool sized for a single-process uvicorn deployment.

Tests construct their own in-memory engine and call
:func:`app.infrastructure.database.pragmas.register_pragmas` against it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.database.pragmas import register_pragmas

# Production database URL. Override via the DATABASE_URL env var.
# Supabase connection strings start with "postgresql://"; SQLAlchemy
# requires "postgresql+psycopg2://" — we normalise that here so the
# raw Supabase URL works without modification.
_raw_url: str = os.environ.get("DATABASE_URL", "sqlite:///data/cse.db")

# Supabase (and some other providers) emit "postgres://" which SQLAlchemy
# 2.x no longer accepts; normalise to "postgresql+psycopg2://".
if _raw_url.startswith("postgres://"):
    _raw_url = "postgresql+psycopg2://" + _raw_url[len("postgres://"):]
elif _raw_url.startswith("postgresql://") and "+psycopg2" not in _raw_url:
    _raw_url = "postgresql+psycopg2://" + _raw_url[len("postgresql://"):]

DATABASE_URL: str = _raw_url

_is_sqlite: bool = DATABASE_URL.startswith("sqlite")


def _ensure_sqlite_directory(url: str) -> None:
    """Create the parent directory for a file-backed SQLite URL if missing."""
    if not url.startswith("sqlite:///"):
        return
    path = url[len("sqlite:///"):]
    if not path or path == ":memory:":
        return
    if "/" not in path:
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


if _is_sqlite:
    _ensure_sqlite_directory(DATABASE_URL)

# Build engine with dialect-appropriate kwargs.
if _is_sqlite:
    engine: Engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        future=True,
    )
    # Apply SQLite PRAGMAs (WAL, foreign_keys=ON, etc.)
    register_pragmas(engine)
else:
    # Postgres: use a modest pool suitable for a single-process uvicorn
    # deployment on Koyeb's free tier (512 MB RAM).
    # pool_pre_ping=True drops stale connections after Supabase's idle
    # timeout (default 5 min on free tier) without crashing requests.
    engine = create_engine(
        DATABASE_URL,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        future=True,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield a request-scoped ``Session`` and close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
