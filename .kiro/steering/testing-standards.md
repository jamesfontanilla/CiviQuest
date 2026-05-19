---
inclusion: always
---
# Testing Standards

## Why These Standards

The project uses a **three-layer test strategy** that mirrors the architecture: repository → service → router. Each layer tests in isolation using the appropriate scope of mocking. This catches bugs at the right layer without over-mocking (which hides real failures) or under-mocking (which creates fragile, slow tests).

---

## Test File Organization

Mirror the app structure under `tests/`:

```
tests/
├── conftest.py              # Shared fixtures (DB engine, session)
└── features/
    └── items/
        ├── test_repository.py
        ├── test_service.py
        └── test_router.py
```

One test file per layer, per feature. Do not mix layers in one file.

---

## Layer Responsibilities

### Repository Tests — Real DB, No Mocks

Test SQL queries against an in-memory SQLite database. Use the `db_session` fixture from `conftest.py`. No mocking.

```python
def test_get_by_title_returns_item(db_session):
    repo = ItemRepository(db=db_session)
    repo.create(ItemCreate(title="Widget", description="A widget"))
    result = repo.get_by_title("Widget")
    assert result is not None
    assert result.title == "Widget"
```

These tests verify that ORM queries, filters, and relationships work against a real database engine.

### Service Tests — Mocked Repository

Test business logic in isolation. Use `MagicMock(spec=RepositoryClass)` — `spec=` catches attribute typos at test time.

```python
def test_get_item_raises_404_when_missing(mock_repo):
    mock_repo.get.return_value = None
    service = ItemService(repository=mock_repo)
    with pytest.raises(HTTPException) as exc_info:
        service.get_item(item_id=999)
    assert exc_info.value.status_code == 404
```

Always assert on `exc_info.value.status_code`, not the string detail (details can change; codes are contractual).

### Router Tests — Mocked Service, HTTP Client

Test HTTP behavior: status codes, request validation, response shape. Use `TestClient` and override dependencies.

```python
app.dependency_overrides[get_item_service] = lambda: mock_service

def test_create_item_returns_201(client, mock_service):
    mock_service.create_item.return_value = ItemResponse(id=1, title="Widget", ...)
    response = client.post("/items/", json={"title": "Widget"})
    assert response.status_code == 201
```

Always call `app.dependency_overrides.clear()` in teardown (or use a fixture that does it).

---

## Fixtures

Define shared fixtures in `conftest.py`. Per-test isolation is mandatory for DB fixtures — use `scope="function"`.

```python
@pytest.fixture(scope="function")
def db_session(db_engine):
    Base.metadata.create_all(bind=db_engine)
    session = SessionLocal(bind=db_engine)
    yield session
    session.close()
    Base.metadata.drop_all(bind=db_engine)
```

---

## Test Data

Use a `_make_item(**kwargs)` factory helper within test files to build test objects with sensible defaults. Do not repeat inline dict construction across tests.

```python
def _make_item(**kwargs):
    defaults = {"title": "Test Item", "description": "desc"}
    return ItemCreate(**{**defaults, **kwargs})
```

---

## Coverage Expectations

- **Repository layer:** All custom query methods must have a test. CRUD inherited from `BaseRepository` does not need re-testing per feature.
- **Service layer:** Every branch (happy path + each exception case) must be covered.
- **Router layer:** Every endpoint must have at minimum a happy-path test and one validation-failure test (e.g., missing required field → 422).

---

## Libraries

| Tool | Purpose |
|------|---------|
| `pytest` | Test runner and fixture system |
| `httpx` / `TestClient` | HTTP-level route testing |
| `pytest-mock` / `MagicMock` | Repository and service mocking |

Do not introduce additional test libraries without team discussion.