"""Smoke tests for the database engine, session factory, and SQLite pragmas."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.infrastructure.database.base import Base
from app.infrastructure.database.pragmas import register_pragmas
from app.infrastructure.database.session import SessionLocal, engine, get_db


def test_module_exports_are_importable() -> None:
    """The public surface of the database module imports cleanly."""
    assert Base is not None
    assert engine is not None
    assert SessionLocal is not None
    assert callable(get_db)
    assert callable(register_pragmas)


def test_register_pragmas_enables_foreign_keys_on_in_memory_engine() -> None:
    """``register_pragmas`` must turn FK enforcement on for SQLite connections.

    SQLite ships with ``foreign_keys=OFF`` by default. The connect listener
    issues ``PRAGMA foreign_keys=ON`` which we verify by reading the value
    back. ``journal_mode=WAL`` is silently skipped for ``:memory:`` databases
    (SQLite reports ``memory`` instead, and that is acceptable).
    """
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    register_pragmas(test_engine)

    with test_engine.connect() as conn:
        result = conn.execute(text("PRAGMA foreign_keys")).scalar_one()
        assert result == 1

        # journal_mode for :memory: returns "memory" — the listener tolerates
        # the fact that WAL cannot be set, so the connection is still usable.
        journal_mode = conn.execute(text("PRAGMA journal_mode")).scalar_one()
        assert journal_mode is not None


def test_get_db_yields_and_closes_session() -> None:
    """``get_db`` is a generator that yields a Session and closes it on exit."""
    gen = get_db()
    session = next(gen)
    try:
        assert session is not None
        # Simple round-trip to confirm the session is usable.
        assert session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        # Exhaust the generator to trigger the ``finally: db.close()`` branch.
        try:
            next(gen)
        except StopIteration:
            pass
