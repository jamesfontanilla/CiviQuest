---
inclusion: always
---
# Code Conventions

## Why These Standards

The project uses **feature-sliced architecture** — each domain (e.g., `items`) owns its models, schemas, repository, service, and router. Consistent structure across features means any developer can navigate an unfamiliar feature using muscle memory, not exploration.

---

## Naming

| Thing | Convention | Example |
|-------|-----------|---------|
| Classes | PascalCase | `ItemService`, `BaseRepository` |
| Functions / methods | snake_case | `get_item`, `list_items` |
| Variables | snake_case | `db_session`, `item_id` |
| Constants | SCREAMING_SNAKE | `DATABASE_URL`, `TEST_DATABASE_URL` |
| Private helpers | leading underscore | `_make_item` |
| Test files | `test_` prefix | `test_service.py` |

---

## File Organization

Every feature lives under `app/features/<feature_name>/` with exactly these files:

```
app/features/items/
├── models.py       # SQLAlchemy ORM model
├── schemas.py      # Pydantic request/response schemas
├── repository.py   # DB access, extends BaseRepository
├── service.py      # Business logic, raises HTTPException
└── router.py       # FastAPI routes, dependency injection
```

Shared infrastructure goes in `app/common/` (schemas, middleware) or `app/infrastructure/` (DB, base classes, external adapters). Do not put shared logic inside a feature directory.

---

## Import Order

1. Standard library (`os`, `typing`, `datetime`)
2. Third-party (`fastapi`, `sqlalchemy`, `pydantic`)
3. Internal (`from app.features.items.models import Item`)

Use absolute imports from the app root. No relative imports (`.` / `..`).

```python
# Good
from app.features.items.models import Item
from app.infrastructure.repositories.base import BaseRepository

# Bad
from ..models import Item
```

---

## Type Hints

All function signatures must have type hints. Return types are mandatory.

```python
def get_item(self, item_id: int) -> Item | None:
    ...
```

Use `Item | None` (Python 3.10+ union syntax), not `Optional[Item]`. Generic classes use `TypeVar`:

```python
ModelType = TypeVar("ModelType")

class BaseRepository(Generic[ModelType]):
    ...
```

---

## Pydantic Schemas

Separate schemas for create, update, and response. Never reuse one schema for all three.

```python
class ItemCreate(BaseModel):
    title: str
    description: str | None = None

class ItemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None

class ItemResponse(BaseModel):
    id: int
    title: str
    model_config = {"from_attributes": True}  # ORM → Pydantic
```

Use `model_dump(exclude_unset=True)` for partial updates so unset fields are not written as `None`.

---

## SQLAlchemy Models

Inherit from `Base` (`app.infrastructure.database.base`). Always include `created_at` / `updated_at` with server-side defaults.

```python
class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

---

## Service Layer Rules

- Services receive a repository instance via constructor injection (not `Depends` directly).
- All error conditions raise `HTTPException` — never return `None` to the router as a signal.
- No DB session access in services; all DB work goes through the repository.

---

## Anti-Patterns

- **Raw SQL strings** — use SQLAlchemy query API always.
- **Business logic in routers** — routers call services; services call repositories.
- **`Optional[X]`** — use `X | None` instead.
- **`model_dump()` in routers** — let FastAPI serialize via `response_model`.
- **Shared mutable state at module level** — use dependency injection.