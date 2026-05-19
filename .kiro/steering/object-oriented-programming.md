---
inclusion: auto
---

# Object-Oriented Programming Principles

Follow these OOP principles when writing backend code.

## Principle 1: Follow Proper Layering

Maintain strict separation of concerns across layers:

- **Handler (Controller)** — the first entrypoint of code, handles HTTP concerns
- **Domain** — where business logic lives
- **Base Domain** — inherited by the domain, contains common functions (e.g., `serialize()`, `__init__(self, data)`)
- **Repository** — where data logic lives, completely decouples data logic from business logic (critical for TDD)
  - **Base Repository** — generic data logic (e.g., base MongoDB or DynamoDB operations)
- **Service** — low-level code that interfaces with your data store (e.g., boto3 code lives only here)

## Principle 2: Classes Must Emulate Real-World Objects

Do NOT use classes as function containers. To use OOP correctly, you must:

- Instantiate an object
- Store data in the instance
- Have instance methods that act on the data inside the instance

Signs you are doing OOP wrong:
- Using too many `@classmethod`s
- Having a verb in your class name (e.g., `OrderProcessor` instead of `Order`)

Create separate classes for distinct entities (e.g., `Customer`, `Order`, `LineItem`).

**RULE: Never expose database-related syntax at the domain level.**

## Principle 3: Standard Methods for OOP

Follow these standard methods so code looks and feels consistent across all projects:

### Class Methods

Rules:
- Must use `cls` as first argument
- Methods that act on the model as a group
- Must include `@classmethod` decorator

Standard class methods:
- `Model.find()` — given a key, find the element. Returns an instance of the found object
- `Model.find_all()` — returns all results (can be paginated), as a list of instantiated objects
- `Model.create()` — creates the element. Returns an instance of the created object
- `Model.where()` — returns filtered results (can be paginated)

### Instance Methods

Rules:
- Must use `self` as first argument
- Methods that act on individual instances of the model

Standard instance methods:
- `obj.serialize()` — return a JSON representation
- `obj.update()` — update the instance
- `obj.save()` — persist the instance
- `obj.delete()` — delete the instance

**All method names must use snake_case.**

## Principle 4: Use Lookup Hashes Instead of "if" Statements

Replace chains of `if/elif` statements with dictionary lookups (lookup hashes) for cleaner, more maintainable code.

## Principle 5: Object Composition

When you have complex data structures:
- Compose objects from smaller component objects
- Instead of cramming all functionality into one big model, delegate responsibilities to subobjects
- Example: A `Cart` object composes `Customer` (with `BillingAddress`, `ShippingAddress`) and a list of `CartItem` objects
- All domains should inherit from `BaseDomain`

## Principle 6: Use Exceptions to Break Flow

- Instead of many nested `if` statements, raise exceptions early
- Use `raise SomeException("message")` to break flow when validation fails
- Let exceptions bubble up to a global handler rather than catching them locally in features

## Principle 7: Database Tables Are Different from OOP Class Entities

Database table structures do not need to map 1:1 to your OOP class hierarchy. Design your classes around domain behavior, not database schema.
