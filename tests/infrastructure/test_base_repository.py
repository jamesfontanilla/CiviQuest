"""Tests for ``BaseRepository`` against a throwaway ORM model.

The ``Item`` model below is defined at module top level so it is registered
on ``Base.metadata`` by the time the ``db_session`` fixture in
``tests/conftest.py`` calls ``Base.metadata.create_all``. Per
``testing-standards.md``, repository tests run against the real in-memory
SQLite engine without mocks; this module owns the only tests for the
inherited CRUD surface.
"""

from __future__ import annotations

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.repositories.base import BaseRepository


class Item(Base):
    """Throwaway ORM model used only by these tests."""

    __tablename__ = "_test_base_repo_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ItemRepository(BaseRepository[Item]):
    """Concrete subclass that wires ``model`` for the test fixture."""

    model = Item


def _make_item(title: str = "Widget") -> Item:
    """Factory helper to build a fresh ORM instance with sensible defaults."""
    return Item(title=title)


def test_create_assigns_id_and_persists(db_session: Session) -> None:
    repo = ItemRepository(db=db_session)
    created = repo.create(_make_item(title="Widget"))

    assert created.id is not None

    fetched = repo.get(created.id)
    assert fetched is not None
    assert fetched.title == "Widget"


def test_get_returns_none_for_missing_id(db_session: Session) -> None:
    repo = ItemRepository(db=db_session)
    assert repo.get(999_999) is None


def test_list_pagination(db_session: Session) -> None:
    repo = ItemRepository(db=db_session)
    for n in range(5):
        repo.create(_make_item(title=f"item-{n}"))

    page = repo.list(skip=2, limit=2)

    assert len(page) == 2
    assert [row.title for row in page] == ["item-2", "item-3"]


def test_update_persists_changes(db_session: Session) -> None:
    repo = ItemRepository(db=db_session)
    created = repo.create(_make_item(title="old"))

    repo.update(created, title="new")

    refetched = repo.get(created.id)
    assert refetched is not None
    assert refetched.title == "new"


def test_delete_removes_row(db_session: Session) -> None:
    repo = ItemRepository(db=db_session)
    created = repo.create(_make_item(title="doomed"))
    item_id = created.id

    repo.delete(created)

    assert repo.get(item_id) is None
