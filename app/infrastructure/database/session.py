"""SQLAlchemy engine, session factory, and FastAPI ``get_db`` dependency.

Importing this module is sufficient to bring the production engine and its
SQLite PRAGMAs online. Tests should construct their own in-memory engine and
call :func:`app.infrastructure.database.pragmas.register_pragmas` against it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.database.pragmas import register_pragmas

# Production database URL. Override via the DATABASE_URL env var per design.md.
DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///data/cse.db")


def _ensure_sqlite_directory(url: str) -> None:
    """Create the parent directory for a file-backed SQLite URL if missing.

    ``sqlite:///data/cse.db`` -> ensures ``data/`` exists.
    ``sqlite:///:memory:`` and non-SQLite URLs are left alone.
    """
    if not url.startswith("sqlite:///"):
        return
    path = url[len("sqlite:///") :]
    if not path or path == ":memory:":
        return
    if "/" not in path:
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


_ensure_sqlite_directory(DATABASE_URL)

# ``check_same_thread=False`` is required because FastAPI worker threads may
# share a connection across requests within a single ``SessionLocal`` lifetime.
# The session itself is per-request, so this does not introduce cross-request
# leakage. ``StaticPool`` is intentionally NOT used here; tests opt in to it
# explicitly when they construct an in-memory engine.
engine: Engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    future=True,
)

# Apply SQLite PRAGMAs (WAL, foreign_keys=ON, etc.) to the production engine.
register_pragmas(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield a request-scoped ``Session`` and close it.

    Usage::

        @router.get("/items")
        def list_items(db: Session = Depends(get_db)) -> ...:
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
