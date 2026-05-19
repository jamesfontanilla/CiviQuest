"""Schema-validation tests for the users slice.

The Pydantic schemas are the public input boundary; if they accept malformed
input the service and repository layers cannot recover. Each test isolates a
single Req-1 rule so a regression is easy to localise.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.features.users.models import AccountState, Category, Role
from app.features.users.schemas import UserCreate, UserResponse


# Baseline payload that satisfies every Req-1 validator. Tests mutate one
# field at a time and assert the relevant rule fails.
_VALID_PAYLOAD: dict[str, object] = {
    "email": "Alice@Example.com",
    "display_name": "Alice",
    "age": 25,
    "category": "PROFESSIONAL",
    "password": "Strong1Pass!",
}


def _make_create(**overrides: object) -> dict[str, object]:
    return {**_VALID_PAYLOAD, **overrides}


def test_user_create_lowercases_email() -> None:
    user = UserCreate(**_make_create(email="MIXED.Case@Example.com"))
    assert user.email == "mixed.case@example.com"


def test_user_create_rejects_short_password() -> None:
    with pytest.raises(ValidationError) as excinfo:
        UserCreate(**_make_create(password="Aa1!aaa"))  # 7 chars
    assert "at least 8 characters" in str(excinfo.value)


def test_user_create_rejects_password_missing_uppercase() -> None:
    with pytest.raises(ValidationError) as excinfo:
        UserCreate(**_make_create(password="strong1pass!"))
    assert "uppercase" in str(excinfo.value)


def test_user_create_rejects_password_missing_digit() -> None:
    with pytest.raises(ValidationError) as excinfo:
        UserCreate(**_make_create(password="StrongPass!"))
    assert "digit" in str(excinfo.value)


def test_user_create_rejects_password_missing_symbol() -> None:
    with pytest.raises(ValidationError) as excinfo:
        UserCreate(**_make_create(password="Strong1Pass"))
    assert "symbol" in str(excinfo.value)


def test_user_create_rejects_age_below_15() -> None:
    with pytest.raises(ValidationError):
        UserCreate(**_make_create(age=14))


def test_user_create_rejects_age_above_100() -> None:
    with pytest.raises(ValidationError):
        UserCreate(**_make_create(age=101))


def test_user_create_rejects_invalid_category() -> None:
    with pytest.raises(ValidationError):
        UserCreate(**_make_create(category="HOBBYIST"))


def test_user_create_rejects_malformed_email() -> None:
    with pytest.raises(ValidationError) as excinfo:
        UserCreate(**_make_create(email="not-an-email"))
    assert "email" in str(excinfo.value).lower()


def test_user_create_accepts_valid_payload() -> None:
    user = UserCreate(**_VALID_PAYLOAD)
    assert user.email == "alice@example.com"
    assert user.category == Category.PROFESSIONAL
    assert user.age == 25
    # ``password`` is round-tripped intact; the service hashes it before
    # persisting, so the schema does not transform it.
    assert user.password == "Strong1Pass!"


def test_user_response_serializes_from_attributes() -> None:
    """``UserResponse`` accepts an object with attribute access (ORM row)."""

    class _Row:
        id = 1
        email = "alice@example.com"
        display_name = "Alice"
        age = 25
        category = "PROFESSIONAL"
        role = "LEARNER"
        account_state = "UNVERIFIED"
        is_banned = False
        tz_name = "UTC"

    resp = UserResponse.model_validate(_Row())
    assert resp.id == 1
    assert resp.role == Role.LEARNER
    assert resp.account_state == AccountState.UNVERIFIED
    assert resp.is_banned is False
