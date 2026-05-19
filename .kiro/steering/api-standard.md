---
inclusion: always
---
# API Standards

## Why These Standards

FastAPI auto-generates OpenAPI docs from code. Consistent conventions ensure the generated docs are navigable, errors are debuggable, and clients can handle responses predictably without reading source code.

---

## URL Structure

- Plural nouns for collections: `/items`, `/users`
- Kebab-case for multi-word resources: `/order-items`
- No trailing slashes on collections (FastAPI redirects these by default — avoid ambiguity)
- Action endpoints should be suffixed with a colon `:`: `/items/:export`
- Feature routers use `prefix` on `APIRouter`; mount via `app.include_router()`

```python
router = APIRouter(prefix="/items", tags=["items"])
```

---

## HTTP Methods & Status Codes

| Operation | Method | Success Code |
|-----------|--------|-------------|
| List      | GET    | 200          |
| Get one   | GET    | 200          |
| Create    | POST   | 201          |
| Update    | PATCH  | 200          |
| Delete    | DELETE | 204          |

Use `PATCH` (not `PUT`) for updates. Pydantic's `exclude_unset=True` supports partial updates natively.

```python
@router.post("/", status_code=status.HTTP_201_CREATED, response_model=ItemResponse)
def create_item(payload: ItemCreate, service: ItemService = Depends(get_item_service)):
    return service.create_item(payload)
```

---

## Pagination

All list endpoints accept `skip` / `limit` query params and return `PaginatedResponse[T]`.

```python
# Request
GET /items/?skip=0&limit=20

# Response
{
  "items": [...],
  "total": 100,
  "skip": 0,
  "limit": 20
}
```

Use `PaginationParams` from `app.common.schemas.request` — it enforces `skip >= 0` and `1 <= limit <= 100`.

---

## Error Responses

All errors use `ErrorResponse` from `app.common.schemas.response`. Shape is always:

```json
{
  "error": {
    "message": "Item not found",
    "code": "NOT_FOUND"
  }
}
```

- **Service layer raises `HTTPException`** with a string `detail`. The global error handler in `app/common/middlewares/error_handler.py` converts unhandled exceptions to 500.
- Never let raw Python exceptions surface — they leak stack traces.
- FastAPI converts 422 validation errors automatically; do not catch and reformat them.

```python
# In service
if not item:
    raise HTTPException(status_code=404, detail="Item not found")
```

---

## Dependency Injection

Wire dependencies through FastAPI's `Depends()`. Each feature exposes a factory function:

```python
def get_item_service(db: Session = Depends(get_db)) -> ItemService:
    return ItemService(repository=ItemRepository(db=db))
```

Tests override via `app.dependency_overrides`. Never instantiate services directly in routes.

---

## Versioning

No versioning prefix currently. When needed, mount routers under `/v1/` at the app level — not at the router level — so individual features don't carry version knowledge.

---

## Health Check

`GET /health` must remain unauthenticated and return `{"status": "ok"}` with 200. Used by deployment infrastructure.