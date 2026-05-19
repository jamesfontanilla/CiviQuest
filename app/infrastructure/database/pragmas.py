"""SQLite PRAGMA registration for a SQLAlchemy engine.

Per design.md (Stack decision) the production engine is SQLite in WAL mode with
``foreign_keys=ON`` enforced at the connection level (SQLite does not enforce
FKs by default). We attach a ``connect`` listener to the *engine instance*
rather than the global ``Engine`` class so the listener only fires for the
SQLite engine and is safe if a future engine targets a different dialect.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.engine import Engine

# Pragmas applied to every new SQLite connection. Order is intentional:
# - journal_mode=WAL must be set before the first write to take effect.
# - synchronous=NORMAL is the recommended pair with WAL (durable, faster).
# - foreign_keys=ON enables FK enforcement (off by default in SQLite).
# - temp_store=MEMORY keeps temp tables/indexes in RAM.
# - mmap_size=268435456 (256 MiB) lets SQLite read the DB via mmap.
_SQLITE_PRAGMAS: tuple[str, ...] = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA mmap_size=268435456",
)


def register_pragmas(engine: Engine) -> None:
    """Register a ``connect`` listener that applies SQLite PRAGMAs.

    Bound to the specific engine instance so non-SQLite engines (and other
    SQLite engines, e.g. test in-memory engines) are unaffected unless they
    also opt in by calling this function.

    ``journal_mode=WAL`` is wrapped in a ``try/except`` because in-memory
    SQLite databases (``sqlite:///:memory:``) do not support WAL and would
    otherwise raise. The remaining pragmas are safe on every SQLite build.
    """

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        # Defensive check: only run for SQLite DBAPI connections. The
        # ``sqlite3`` stdlib module's Connection class lives in module
        # ``sqlite3`` (or ``_sqlite3``); pysqlite3 mirrors the same name.
        module_name = type(dbapi_connection).__module__ or ""
        if "sqlite" not in module_name:
            return

        cursor = dbapi_connection.cursor()
        try:
            for pragma in _SQLITE_PRAGMAS:
                try:
                    cursor.execute(pragma)
                except Exception:
                    # journal_mode=WAL is the only pragma that can fail on
                    # in-memory databases; the others tolerate ``:memory:``.
                    # Swallow narrowly so a single unsupported pragma never
                    # prevents the connection from opening.
                    if "journal_mode" not in pragma:
                        raise
        finally:
            cursor.close()
