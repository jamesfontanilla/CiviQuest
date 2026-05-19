---
inclusion: auto
---

# Best Practices for REST APIs

Follow these standards when designing and implementing REST API endpoints.

## Define APIs with OpenAPI 3.0

All APIs should be defined using the OpenAPI 3.0 specification.

## URL Design Rules

### Path Conventions
- All paths must be **kebab-case** (e.g., `/order-items`)
- Use identifiers for specific resources (e.g., `/products/{product_id}`)

### Versioning
- A clear version strategy must be in place
- Format: `<major-version>/<subsystem>/<resource>`
- Examples: `v1/inventory/products`, `v1/orders/checkouts`

### Resource-Centered URLs
- URLs must be centered around **resources** (nouns, not verbs): "products", "collections", "checkouts"
- Resources must be **plural**

### API Vocabulary
- Maintain a consistent API vocabulary so that naming is uniform throughout the API

## Standard Methods vs. Custom Methods

### Standard Methods
- Standard CRUD methods of a REST resource are preferred over custom methods
- Standard methods must have **no side-effects**. If a method has side-effects, it should be a custom method

### Custom Methods
- Should be indicated by a colon `:` (e.g., `/orders/{id}:cancel`)
- Should always be a **POST** method

## Request Sanitation Standards

All incoming request data must be validated and sanitized before processing.

## HTTP Status Codes

Use expressive HTTP status codes:

### 1xx — Informational
- `100` — Operation in progress

### 2xx — Success
- `200` — OK
- `201` — Created
- `204` — No Content (for DELETE methods)

### 4xx — Client Error
- `400` — Generic error on the request
- `401` — Unauthenticated (user does not have authentication credentials)
- `403` — Unauthorized/Forbidden (user doesn't have permissions)
- `404` — Not Found
- `405` — Method Not Allowed (method is not available and we have no plan to implement it)
- `409` — Conflict (object can't be created because it conflicts with an existing object)
- `422` — Params Error (validation failure)

### 5xx — Server Error
- `500` — Generic server error
- `501` — Not Implemented (method not available but will be soon)
