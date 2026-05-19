"""Generic CRUD repository.

``BaseRepository[ModelType]`` is the shared parent of every feature-specific
repository under ``app/features/*/repository.py``. It is intentionally
ORM-only: the service layer is responsible for translating Pydantic schemas
into ORM instances before calling :meth:`BaseRepository.create` or
:meth:`BaseRepository.update`. Keeping the base ORM-only avoids coupling the
infrastructure layer to Pydantic and lets feature subclasses choose their own
schema-aware overloads.

Per ``code-conventions.md``:

- The session is provided via constructor injection (``db: Session``); there
  is no module-level state, no singleton, and no connection caching.
- All queries use the SQLAlchemy 2.0 ``select(...)`` / ``Session.execute``
  style so the codebase migrates cleanly when the legacy 1.x ``Session.query``
  surface is eventually removed.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.database.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Generic CRUD repository over a single ORM model.

    Subclasses set the ``model`` class attribute to the ORM class they own and
    inherit the five operations below. Feature-specific queries live on the
    subclass (e.g. ``UserRepository.get_by_email``); inherited CRUD does not
    need to be re-tested per feature (see ``testing-standards.md``).

    Example::

        class ItemRepository(BaseRepository[Item]):
            model = Item

            def get_by_title(self, title: str) -> Item | None:
                stmt = select(Item).where(Item.title == title)
                return self.db.execute(stmt).scalar_one_or_none()

    Notes:
        ``create`` and ``update`` accept fully-built ORM instances rather than
        Pydantic schemas. The service layer is responsible for the
        ``SchemaCreate -> ORM`` translation. Feature subclasses are free to
        override these methods with Pydantic-aware variants when the slice
        wants the convenience.
    """

    model: type[ModelType]

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: Any) -> ModelType | None:
        """Return the row with primary key ``id`` or ``None`` if absent.

        Uses ``Session.get`` which performs an indexed primary-key lookup and
        consults the identity map first, avoiding a SQL round trip when the
        instance is already attached.
        """
        return self.db.get(self.model, id)

    def list(self, skip: int = 0, limit: int = 20) -> Sequence[ModelType]:
        """Return up to ``limit`` rows starting at offset ``skip``.

        Pagination bounds are enforced upstream by ``PaginationParams``
        (``skip >= 0``, ``1 <= limit <= 100``); the repository trusts its
        callers and does not re-validate.
        """
        stmt = select(self.model).offset(skip).limit(limit)
        return self.db.execute(stmt).scalars().all()

    def create(self, obj_in: ModelType) -> ModelType:
        """Persist ``obj_in`` and return it with server-side defaults applied.

        The instance is added, the transaction is committed, and the row is
        refreshed so callers see fields populated by the database (primary
        keys, ``created_at``/``updated_at`` server defaults, and so on).
        """
        self.db.add(obj_in)
        self.db.commit()
        self.db.refresh(obj_in)
        return obj_in

    def update(self, obj_in: ModelType, **fields: Any) -> ModelType:
        """Apply ``fields`` to ``obj_in``, commit, and refresh.

        Subclasses may override this with a Pydantic-aware version that takes
        an ``XxxUpdate`` schema and calls ``model_dump(exclude_unset=True)``
        before delegating here.
        """
        for key, value in fields.items():
            setattr(obj_in, key, value)
        self.db.commit()
        self.db.refresh(obj_in)
        return obj_in

    def delete(self, obj_in: ModelType) -> None:
        """Remove ``obj_in`` from the database and commit."""
        self.db.delete(obj_in)
        self.db.commit()
