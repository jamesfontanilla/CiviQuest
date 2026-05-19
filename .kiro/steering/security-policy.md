---
inclusion: always
---
# Security Policies

## Why These Standards

The app currently has no authentication layer, but the infrastructure is designed to add one without restructuring. These policies prevent common vulnerabilities at the layers that already exist (input validation, SQL, error handling) and define the expected security shape when auth is added.

---

## Input Validation

**All external input is validated by Pydantic before reaching service or repository code.** Never bypass Pydantic by accepting raw `dict` or `Any` from a request.

FastAPI rejects malformed requests with 422 automatically. Do not catch and swallow these — let them surface so clients know what to fix.

```python
# Good — Pydantic enforces types and constraints
@router.post("/items/")
def create_item(payload: ItemCreate, ...):  # 422 if invalid
    ...

# Bad — raw dict from request, no validation
@router.post("/items/")
async def create_item(request: Request):
    data = await request.json()  # unvalidated
    ...
```

Add field-level constraints in Pydantic when the domain requires them:

```python
class ItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    price: float = Field(gt=0)
```

---

## SQL Injection Prevention

Use SQLAlchemy's query API exclusively. Never use string formatting or f-strings to build SQL.

```python
# Good
self.db.query(Item).filter(Item.title == title).first()

# Bad — SQL injection vector
self.db.execute(f"SELECT * FROM items WHERE title = '{title}'")
```

SQLAlchemy parameterizes all values automatically when using the ORM or `text()` with `bindparams`.

---

## Error Handling & Information Leakage

The global error handler in `app/common/middlewares/error_handler.py` catches unhandled exceptions and returns a generic 500 without a stack trace. **Never remove or bypass this middleware.**

Rules:
- Services raise `HTTPException` with user-safe `detail` strings — no internal paths, query text, or exception messages.
- Log the full exception server-side (structured logging via the request logging middleware); send only a safe message to the client.
- Do not expose the `DATABASE_URL` or any credential in any response, log line, or error detail.

```python
# Good
raise HTTPException(status_code=404, detail="Item not found")

# Bad — leaks internals
raise HTTPException(status_code=500, detail=str(e))
```

---

## Authentication (When Implemented)

The `ExternalServiceBase` ABC (`app/infrastructure/external/base.py`) is the integration point for JWT/OAuth providers. Mount auth checks as FastAPI dependencies — not inside service or repository methods — so they can be tested independently and overridden in tests.

Expected pattern:
```python
async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    # verify JWT, raise 401 if invalid
    ...

@router.get("/items/{id}")
def get_item(item_id: int, user: User = Depends(get_current_user), ...):
    ...
```

- `401 Unauthorized` — missing or invalid token
- `403 Forbidden` — valid token but insufficient permissions
- Never return 404 to hide resource existence from unauthenticated users; return 401/403 first

---

## Secrets & Configuration

- All secrets (`DATABASE_URL`, API keys, JWT secrets) must come from environment variables.
- No secrets in source code, comments, or committed `.env` files.
- `.env` is in `.gitignore` — keep it there. Use `.env.example` with placeholder values for onboarding.

---

## Security Tooling

Run these as part of CI / pre-commit:

| Tool | What It Checks |
|------|---------------|
| `bandit` | Python security anti-patterns (hardcoded passwords, unsafe `eval`, etc.) |
| `mypy` | Type safety — catches `None` dereferences and type mismatches before runtime |
| `ruff` | Linting including some security-adjacent rules |

Run bandit: `bandit -r app/`

Fix all `HIGH` severity bandit findings before merging. `MEDIUM` findings require justification in the PR.

---

## Request Tracing

Every request receives an `X-Request-ID` header (added by `LoggingMiddleware`). Include this ID in all bug reports and log queries. Do not strip it in responses — clients use it to correlate their logs with server logs.