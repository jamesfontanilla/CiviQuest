---
inclusion: auto
---

# React + Vite SPA — Feature-Sliced Architecture Guide

## Philosophy

Organize frontend code **by feature**, not by technical role. Each feature maps to a user-facing capability (e.g., "create user", "product list") and owns its own components, hooks, API calls, validation, and types.

Key principle: **Code that changes together lives together.** Shared UI primitives and utilities live outside features.

Why feature-sliced:
- A developer working on "edit product" never touches "user list" files
- Each feature can be lazy-loaded for performance
- Adding a new page/feature means adding a new folder — you don't modify existing features
- Scales from 5 features to 50 without becoming a mess

## Repository Structure

```
src/
├── app/
│   ├── providers.tsx        # All context providers composed
│   ├── router.tsx           # Route definitions (URL → feature page)
│   └── query-client.ts     # TanStack Query defaults
├── features/
│   └── <domain>/
│       └── <feature-name>/
│           ├── types.ts             # Feature-scoped types
│           ├── schema.ts            # Zod validation schema
│           ├── use<Feature>.ts      # TanStack Query hook
│           ├── <Feature>Form.tsx    # Form UI component
│           └── <Feature>Page.tsx    # Page component (route target)
├── infrastructure/
│   ├── api/
│   │   ├── client.ts        # Axios instance with interceptors
│   │   └── endpoints.ts    # Centralized API path constants
│   ├── config/
│   │   └── env.ts           # Typed environment variables
│   └── stores/              # Zustand stores (client-only state)
├── shared/
│   ├── components/          # Dumb UI primitives (Button, Input, Table)
│   └── types/
│       └── api.ts           # API envelope types
├── tests/
│   ├── mocks/
│   │   ├── handlers.ts     # MSW request handlers
│   │   ├── server.ts       # MSW server setup
│   │   └── setup.ts        # Test setup
│   └── features/           # Tests mirroring feature structure
└── main.tsx                 # Entry point
```

## Layer Responsibilities

### app/ — Application Shell
- `providers.tsx` — Wraps the app in all context providers. Single place to add new providers.
- `router.tsx` — All routes declared in one file. Each route points to a feature's page component.
- `query-client.ts` — TanStack Query default configuration.

### Feature Slice Anatomy

Each feature owns: page, components, hooks, validation schema, and types.

- **types.ts** — Feature-scoped request/response types (mirror backend schemas but owned independently)
- **schema.ts** — Zod client-side form validation (UX optimization; backend is source of truth)
- **use<Feature>.ts** — TanStack Query mutation/query hook wrapping the API call
- **<Feature>Form.tsx** — Form state, Zod validation, calls the mutation hook
- **<Feature>Page.tsx** — Route target, composes feature components, handles page-level concerns

### Validation Responsibility Split

| What | Where | Why |
|------|-------|-----|
| Field format, required, length | schema.ts (Zod) | Instant UX feedback, no network round trip |
| Business rules (uniqueness, auth) | Backend handler.py | Requires DB state the frontend doesn't have |
| Final source of truth | Backend schemas.py | Server never trusts the client |

### Infrastructure Layer
- **api/client.ts** — Single Axios instance with base URL, headers, error interceptor
- **api/endpoints.ts** — All API paths centralized. One file to update when backend routes change.
- **config/env.ts** — Typed environment variables
- **stores/** — Zustand for client-only state (NOT for server/API data)

### State Ownership

| State type | Owner | Example |
|-----------|-------|---------|
| Server/API data | TanStack Query | user list, product details |
| Form input | Component useState | email field, name field |
| Global UI state | Zustand store | sidebar open, toast queue |
| URL state | React Router | current page, route params |

## Best Practices Checklist

1. **One feature folder = one user-facing operation.** `create-user`, `user-list`, `edit-user` are separate folders.
2. **Pages are thin.** They compose feature components and handle layout. No API calls directly in pages.
3. **Hooks wrap TanStack Query.** Every API call goes through a `useXxx` hook. Components never call `apiClient` directly.
4. **Zod validates forms client-side.** Instant feedback, but backend is always source of truth.
5. **Types are feature-scoped.** `CreateUserRequest` and `UpdateUserRequest` are separate types in separate features.
6. **Shared components are dumb.** Button, Input, Table — receive props and render. No API calls, no business logic.
7. **Zustand is for client-only state.** API data belongs in TanStack Query.
8. **API paths live in endpoints.ts.** One file to update when backend routes change.
9. **Axios interceptors handle error transformation globally.** Features receive clean error messages.
10. **Tests use MSW to mock the API.** No real network calls.
11. **Lazy-load feature pages.** Use `React.lazy()` in the router for code splitting.
12. **Never import from one feature into another.** Shared needs go in `shared/`.

## How to Add a New Feature

Example: Adding "Create Order" (POST /api/v1/orders):

1. Create `src/features/orders/create-order/`
2. Add `types.ts` — define `CreateOrderRequest` and `CreateOrderResponse`
3. Add `schema.ts` — Zod schema for form validation
4. Add `useCreateOrder.ts` — TanStack Query mutation hook
5. Add `CreateOrderForm.tsx` — form component using the schema and hook
6. Add `CreateOrderPage.tsx` — page component that renders the form
7. Add the route in `app/router.tsx`
8. Add `API_ENDPOINTS.ORDERS` in `infrastructure/api/endpoints.ts`
9. Add test handlers in `tests/mocks/handlers.ts`
10. Add `tests/features/orders/create-order.test.tsx`

You never touch existing feature files.

## Anti-Patterns to Avoid

- **API calls in components** — always go through a `useXxx` hook wrapping TanStack Query
- **Business logic on the frontend** — frontend validates form input for UX; business rules belong on the backend
- **Shared types across features** — similar types evolve independently, keep them separate
- **Giant utils/ folder** — feature-specific utilities stay in that feature; only truly shared helpers go in `shared/`
- **Zustand for server data** — if data comes from an API, use TanStack Query
- **Cross-feature imports** — if a feature needs data from another domain, it calls the API via its own hook
- **Inline API URLs** — always use `API_ENDPOINTS` constants
