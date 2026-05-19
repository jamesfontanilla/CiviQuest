"""SQLAlchemy declarative ``Base`` for all ORM models.

Every feature's ``models.py`` imports ``Base`` from this module. ``Base.metadata``
is what Alembic (or, for MVP, ``Base.metadata.create_all``) reflects against.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for ORM models.

    Subclasses register on ``Base.metadata`` at import time. Tests rely on
    importing the feature's models module before calling ``create_all`` so
    every table is registered.
    """
