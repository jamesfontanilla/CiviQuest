"""Abstract base class for external-service adapters.

The ``ExternalServiceBase`` ABC is the integration point for adapters that
talk to anything outside the FastAPI process: SMTP servers, JWT/OAuth
providers, file IO, future webhooks, etc. It is intentionally minimal so
each concrete adapter can expose the small, named surface it needs without
inheriting accidental coupling.

Per ``security-policy.md`` (Authentication section), this is the seam where
JWT/OAuth providers will plug in once auth is added; mounting auth as
adapters that subclass this ABC keeps the service and repository layers
ignorant of transport concerns.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ExternalServiceBase(ABC):
    """Base class for adapters to external systems (SMTP, OAuth, file IO).

    Concrete subclasses MUST implement :meth:`health_check`. Other methods
    depend on the integration. The contract is intentionally minimal: each
    concrete adapter exposes a small, named surface.

    Subclasses should accept their config via constructor injection (NOT
    reading env vars themselves), so tests can pass overrides without
    monkeypatching the environment.
    """

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the adapter can reach its dependency."""
