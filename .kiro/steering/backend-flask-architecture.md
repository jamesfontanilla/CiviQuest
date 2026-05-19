---
inclusion: auto
---

# Python Flask Backend — Feature-Sliced Architecture Guide

## Philosophy

This architecture slices by **endpoint/feature**, not by domain or technical layer. Each feature folder maps to a specific API operation (e.g., `create_user`, `get_product_by_id`) and owns exactly three things: the endpoint definition, the business logic handler, and the schemas (input validation + serialization).

Everything else — models, repositories, shared utilities — lives outside the feature folders in their proper homes.

Key principle: **One endpoint, one folder. Shared resources live in shared places.**

Why this approach:
- Each feature is a single, self-contained unit of work
- Adding a new endpoint means adding a new folder — you never modify existing feature files
- Repositories and models are shared resources — they don't belong to any single feature
- Testing mirrors features 1:1 in a dedicated test folder

## Repository Structure

```
src/
├── app.py                          # App factory
├── extensions.py                   # Flask extension instances
├── config.py                       # Environment-based config classes
├── features/
│   └── <domain>/
│       └── <feature_name>/
│           ├── __init__.py
│           ├── endpoint.py         # Thin HTTP boundary
│           ├── handler.py          # Business logic
│           └── schemas.py          # Marshmallow validation & serialization
├── domain/
│   └── <entity>.py                 # Pure SQLAlchemy model definitions
├── infrastructure/
│   ├── repositories/
│   │   ├── base_repository.py     # Generic CRUD operations
│   │   └── <entity>_repository.py # Entity-specific queries
│   └── base_model.py              # Timestamp mixin
├── common/
│   ├── exceptions.py              # Custom exception classes
│   ├── error_handler.py           # Global exception handler middleware
│   └── responses.py               # Standardized response helpers
└── tests/
    ├── conftest.py                # Shared fixtures
    └── features/
        └── <domain>/
            └── test_<feature_name>.py
```

## Layer Responsibilities

### Feature Slice Anatomy

Each feature = one API operation. Three files, clear responsibilities:

#### endpoint.py — Thin HTTP Boundary
Parses the request, delegates to the handler, returns the response. Nothing else.

#### handler.py — Business Logic
Where decisions are made. Calls repositories, validates business rules that go beyond schema validation (uniqueness, authorization, cross-field logic involving DB state), and orchestrates the operation.

#### schemas.py — Input Validation AND Serialization
Single source of truth for both validating incoming data and shaping outgoing responses using Marshmallow:
- **Request schemas** — required fields, types, constraints (min/max length, regex, allowed values), custom field-level validators. `.load()` both deserializes and validates.
- **Response schemas** — defines what gets serialized back to the client via `.dump()`.

### Validation Responsibility Split

| What | Where | Example |
|------|-------|---------|
| Type checking, required fields, format | schemas.py via Marshmallow | email format, string length |
| Custom field-level rules | schemas.py via `@validates` | whitespace-only rejection |
| Cross-field validation (input only) | schemas.py via `@validates_schema` | "end_date must be after start_date" |
| Business rules requiring DB state | handler.py | email uniqueness, entity existence |
| Response shaping | schemas.py via response schema | which fields to expose, `dump_only` |

### Domain Layer — Models Only
Pure SQLAlchemy definitions. No business logic, no queries, no validation. Shared data structures that multiple features reference.

### Infrastructure Layer
- **base_repository.py** — Generic CRUD operations (create, get_by_id, get_all, update, delete)
- **Entity repositories** — Extend base with custom queries only
- **base_model.py** — Timestamp mixin (created_at, updated_at)

### Common Layer
- **exceptions.py** — Custom exception classes
- **error_handler.py** — Global exception handler that catches all exceptions and returns standardized error responses
- **responses.py** — Standardized response format helpers

## Best Practices Checklist

1. **One feature folder = one endpoint.** `create_user`, `list_users`, `update_user` are separate folders.
2. **Endpoints are dumb.** Parse request, call `.load()` for validation, call handler, call `.dump()` for response. No `if` logic, no `db.session`.
3. **Schemas own ALL input validation.** Type checking, format constraints, field-level rules, cross-field rules — all in `schemas.py` using Marshmallow. If it can be validated without hitting the database, it belongs in the schema.
4. **Handlers own business rules that require state.** Uniqueness checks, authorization, anything needing a DB lookup. Handlers never re-validate what schemas already enforce.
5. **Never duplicate validation.** If the schema checks email format, the handler doesn't check it again. If the handler checks uniqueness, the schema doesn't attempt it.
6. **Schemas are feature-scoped.** `CreateUserRequest` and `UpdateUserRequest` are separate — they evolve independently. Never share schemas across features.
7. **Repositories are the only files that touch `db.session`.** Handlers call repository methods, never raw queries.
8. **Base repository handles generic CRUD.** Entity repos only add custom queries.
9. **Domain models are plain SQLAlchemy.** No methods, no validation, no business logic.
10. **Exceptions are raised, never caught in features.** The global exception handler middleware in `common/` handles everything.
11. **Cross-feature calls go through repositories, not handlers.**
12. **Tests mirror features 1:1 in the `tests/` directory.**

## How to Add a New Feature

Example: Adding POST /api/v1/orders:

1. Create `src/features/orders/create_order/` with `__init__.py`, `endpoint.py`, `handler.py`, `schemas.py`
2. In `schemas.py`: define `CreateOrderRequest` with all input validation rules and `CreateOrderResponse` for serialization
3. If the `Order` model doesn't exist yet, add `src/domain/order.py`
4. If `OrderRepository` doesn't exist yet, add `src/infrastructure/repositories/order_repository.py` extending `BaseRepository[Order]`
5. Write the handler with business logic, calling the repository
6. Wire up the endpoint (thin — load schema, call handler, dump response)
7. Register the blueprint in `app.py` → `_register_features()`
8. Run `flask db migrate -m "add orders table"` and `flask db upgrade`
9. Add `tests/features/orders/test_create_order.py`

You never touch existing feature files.

## Anti-Patterns to Avoid

- **Fat endpoints** — business logic or validation leaking into `endpoint.py`. Validation belongs in schemas, logic in handlers.
- **Validation in handlers that schemas should own** — if it doesn't need a DB call, put it in the schema.
- **Shared schemas across features** — tempting but dangerous. Each feature's schemas evolve independently.
- **Handlers calling other handlers** — use repositories or extract shared logic into `common/utils/`.
- **Models with methods** — keep domain models as pure data definitions.
- **Catching exceptions in features** — let them bubble up to the global handler.
- **Putting tests inside feature folders** — tests live in `tests/` only.
