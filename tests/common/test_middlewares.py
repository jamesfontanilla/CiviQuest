"""Property + unit tests for the middlewares from Task 1.5.

Validates two correctness properties from the design's Property catalog:

* **Property 33: Audit log redaction** — for any payload containing a
  redaction-listed field name, the redacted form contains ``***REDACTED***``
  and never the original value.
* **Property 34: Request correlation propagation** — the response
  ``X-Request-ID`` equals ``request.state.request_id``. When the client
  provides the header it is echoed verbatim; when absent a fresh UUIDv4 is
  generated.

Also exercises one happy/unhappy branch of :class:`AuthMiddleware` to confirm
its permissive contract: it never raises, decodes valid bearer tokens, and
swallows invalid ones.

**Validates: Requirements 21.3, 21.4**
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, assume, given, settings, strategies as st
from starlette.requests import Request

from app.common.middlewares.auth import AuthMiddleware
from app.common.middlewares.logging import (
    REDACTED_KEYS,
    RequestLoggingMiddleware,
    redact,
)

# --- Strategies -------------------------------------------------------------

_REDACTED_VALUE = "***REDACTED***"


def _value_contains(haystack: Any, needle: str) -> bool:
    """Recursively check whether ``needle`` appears in any string *value*.

    Walks dict values (not keys), list elements, and stringifies leaves.
    Used by the redaction leak-check to avoid false positives where the
    needle appears in a key name (e.g. ``'w'`` is a substring of
    ``'password'``).
    """
    if isinstance(haystack, dict):
        return any(_value_contains(v, needle) for v in haystack.values())
    if isinstance(haystack, list):
        return any(_value_contains(v, needle) for v in haystack)
    if isinstance(haystack, str):
        return needle in haystack
    return False

# Keys we are allowed to use as "safe" (non-redacted) field names. We blacklist
# surrogate code points (Cs) because JSON / dict iteration tooling stumbles on
# them, and we filter to ensure the lowercase form is not in the redacted set.
_safe_key_strategy = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=8,
).filter(lambda s: s.lower() not in REDACTED_KEYS)

_redacted_key_strategy = st.sampled_from(sorted(REDACTED_KEYS))

# Leaf values for nested structures. NaN excluded because equality assertions
# downstream would behave unexpectedly.
_leaf_strategy = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.text(max_size=20),
    st.floats(allow_nan=False, allow_infinity=False),
)


# --- Property 33: Redaction --------------------------------------------------


@given(
    redacted_key=_redacted_key_strategy,
    secret=st.text(min_size=1, max_size=32).filter(
        lambda s: s != _REDACTED_VALUE and s not in _REDACTED_VALUE
    ),
    safe_payload=st.dictionaries(_safe_key_strategy, _leaf_strategy, max_size=4),
)
@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=100)
def test_redact_replaces_listed_keys(
    redacted_key: str, secret: str, safe_payload: dict[str, Any]
) -> None:
    """For every redaction-listed key, the secret is replaced and never leaks.

    We use ``repr(result)`` as a coarse leak detector: if the original ``secret``
    survives anywhere in the redacted output (including nested locations), the
    repr will contain it. Cheap and effective.

    Validates: Requirement 21.3 (redaction).
    """
    payload: dict[str, Any] = dict(safe_payload)
    payload[redacted_key] = secret

    # Skip examples where the secret happens to appear inside unrelated safe
    # values: the leak-check below would false-positive on those without
    # telling us anything about redaction correctness.
    assume(not _value_contains(safe_payload, secret))

    result = redact(payload)

    assert result[redacted_key] == _REDACTED_VALUE
    # The original secret must not appear in any *value* of the redacted
    # output. We deliberately walk values only — keys are public field names
    # like ``"password"`` and may legitimately share substrings with secrets.
    assert not _value_contains(result, secret)
    # Non-listed keys are preserved untouched.
    for k, v in safe_payload.items():
        if k == redacted_key:
            continue
        assert result[k] == v


def test_redact_handles_nested_dicts_and_lists() -> None:
    """Nested redacted keys are caught; sibling fields are preserved."""
    payload = {
        "users": [
            {"password": "supersecret", "name": "alice"},
            {"name": "bob"},
        ],
        "outer_safe": "ok",
    }

    result = redact(payload)

    assert result["users"][0]["password"] == _REDACTED_VALUE
    assert result["users"][0]["name"] == "alice"
    assert result["users"][1] == {"name": "bob"}
    assert result["outer_safe"] == "ok"
    assert "supersecret" not in repr(result)


def test_redact_is_case_insensitive() -> None:
    """Mixed-case variants of redacted keys are still redacted."""
    payload = {"Password": "x", "PASSWORD": "y", "AuThOrIzAtIoN": "z"}

    result = redact(payload)

    assert result["Password"] == _REDACTED_VALUE
    assert result["PASSWORD"] == _REDACTED_VALUE
    assert result["AuThOrIzAtIoN"] == _REDACTED_VALUE


def test_redact_returns_new_object() -> None:
    """``redact`` does not mutate its input."""
    original = {
        "password": "secret",
        "nested": {"token": "t", "name": "kept"},
    }
    snapshot = {
        "password": "secret",
        "nested": {"token": "t", "name": "kept"},
    }

    result = redact(original)

    assert original == snapshot
    assert result is not original
    assert result["nested"] is not original["nested"]


# --- Property 34: Request correlation ---------------------------------------


def _make_app() -> FastAPI:
    """Build a minimal app that mounts only the logging middleware."""
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/echo")
    def echo(request: Request) -> dict[str, str]:
        return {"rid": request.state.request_id}

    return app


def test_request_id_is_echoed_when_client_provides_one() -> None:
    """A client-supplied ``X-Request-ID`` is bound and echoed verbatim."""
    client = TestClient(_make_app())
    resp = client.get("/echo", headers={"X-Request-ID": "client-supplied-123"})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == "client-supplied-123"
    assert resp.json()["rid"] == "client-supplied-123"


def test_request_id_is_generated_when_client_omits() -> None:
    """Absent header yields a fresh UUIDv4 that is both bound and echoed."""
    client = TestClient(_make_app())
    resp = client.get("/echo")
    assert resp.status_code == 200
    rid = resp.headers["X-Request-ID"]
    parsed = uuid.UUID(rid)
    assert parsed.version == 4
    assert resp.json()["rid"] == rid


@given(
    client_id=st.text(
        alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E),
        min_size=1,
        max_size=64,
    )
)
@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=50)
def test_request_id_round_trip(client_id: str) -> None:
    """For any header-safe non-empty string, the value round-trips intact.

    The strategy is constrained to printable ASCII (excluding space and
    control characters) — that is the byte set HTTP/1.1 actually permits in a
    header value, which is what a real client could ever send.

    Validates: Requirement 21.4 (correlation propagation).
    """
    client = TestClient(_make_app())
    resp = client.get("/echo", headers={"X-Request-ID": client_id})
    assert resp.headers["X-Request-ID"] == client_id
    assert resp.json()["rid"] == client_id


# --- Auth middleware permissive contract ------------------------------------


def _make_app_with_auth() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/probe")
    def probe(request: Request) -> dict[str, Any]:
        return {"claims": request.state.token_claims}

    return app


def test_auth_middleware_does_not_block_unauthenticated_requests() -> None:
    """No header → request reaches the handler with ``token_claims = None``."""
    client = TestClient(_make_app_with_auth())
    resp = client.get("/probe")
    assert resp.status_code == 200
    assert resp.json()["claims"] is None


def test_auth_middleware_decodes_valid_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid bearer tokens populate ``request.state.token_claims``."""
    monkeypatch.setenv("JWT_SECRET", "t-32byte-secret-padding-padding!!")
    from app.infrastructure.security.jwt import encode_token

    token, _claims = encode_token(sub="42")
    client = TestClient(_make_app_with_auth())
    resp = client.get("/probe", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["claims"]["sub"] == "42"


def test_auth_middleware_swallows_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed tokens leave ``token_claims = None`` (no 401 from middleware)."""
    monkeypatch.setenv("JWT_SECRET", "t-32byte-secret-padding-padding!!")
    client = TestClient(_make_app_with_auth())
    resp = client.get("/probe", headers={"Authorization": "Bearer not.a.token"})
    assert resp.status_code == 200
    assert resp.json()["claims"] is None
