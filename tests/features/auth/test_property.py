"""Property-based tests for the auth state machines (Task 4.8).

Each test is a hypothesis ``@given``-driven property that exercises the
auth service across many inputs. Shared mock-factory helpers live in
``_helpers.py``; the property tests reuse them so the fixtures cannot
drift from the unit-test surface.

Validates:
- Property 1: Password rule completeness (Req 1.3)
- Property 2: Age range bounds (Req 1.4)
- Property 8: Session token validity window (Req 3.1)
- Property 9: Login lockout (Req 3.3)
- Property 10: Forgot-password enumeration resistance (Req 4.2)
- Property 11: Password reset invalidates all sessions (Req 4.4)

Hypothesis settings:
- ``deadline=None`` because bcrypt verify (real, cost-12) is occasionally
  slow enough to blow the default 200ms-per-example deadline; ``max_examples``
  bounds total wall-clock time instead.
- ``HealthCheck.too_slow`` and ``HealthCheck.function_scoped_fixture``
  suppressed for the same reason.
- Pure-validation properties (1, 2, 9, 10) use ``max_examples=100`` since
  each example is cheap.
- Properties that hit real bcrypt or JWT machinery (8, 11) use
  ``max_examples=20`` to keep runtime under a few seconds.
"""

from __future__ import annotations

import string
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings, strategies as st
from pydantic import ValidationError

from app.features.auth.schemas import (
    PasswordResetConfirmRequest,
    PasswordResetRequest,
)
from app.features.users.schemas import (
    UserCreate,
    _PASSWORD_SYMBOLS,
    validate_password,
)
from tests.features.auth._helpers import (
    _RIGHT_PASSWORD,
    _TEST_JWT_SECRET,
    _make_service,
    _make_user,
)

# Common settings: bcrypt + JWT operations are unpredictable enough that
# we disable per-example deadlines.
_PBT_SETTINGS = dict(
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
    deadline=None,
)


# --- Property 1: Password rule completeness --------------------------------


def _passes_rules(p: str) -> bool:
    """Mirror of Req 1.3 password rules used as the property's reference."""
    return all(
        [
            len(p) >= 8,
            any(c.isupper() for c in p),
            any(c.islower() for c in p),
            any(c.isdigit() for c in p),
            any(c in _PASSWORD_SYMBOLS for c in p),
        ]
    )


# Restrict the alphabet so hypothesis explores the "interesting" character
# classes (upper / lower / digit / symbol / non-ASCII letter) frequently
# rather than wandering through millions of code points that all behave the
# same way for the validator.
_password_alphabet = (
    string.ascii_letters
    + string.digits
    + "".join(_PASSWORD_SYMBOLS)
    + " "  # exercises the "neither letter, digit, nor allowed symbol" branch
    + "ñ"  # non-ASCII letter — should NOT count as upper/lower in any way the
    # validator wouldn't already accept (Python str.isupper/islower handle it)
)


@given(p=st.text(alphabet=_password_alphabet, min_size=0, max_size=20))
@settings(max_examples=100, **_PBT_SETTINGS)
def test_property_1_password_rule_completeness(p: str) -> None:
    """Property 1 (Req 1.3): validate_password accepts iff all 5 rules hold.

    The reference implementation in ``_passes_rules`` mirrors the rule set
    documented in Req 1.3. The property is the equivalence:

        validate_password(p) succeeds  <==>  _passes_rules(p) is True

    No mocking — ``validate_password`` is the function under test.
    """
    if _passes_rules(p):
        # Should pass without raising.
        assert validate_password(p) == p
    else:
        with pytest.raises(ValueError):
            validate_password(p)


# --- Property 2: Age range bounds ------------------------------------------

# Baseline payload with every field except age satisfying its validator.
_BASE_SIGNUP_PAYLOAD: dict[str, object] = {
    "email": "alice@example.com",
    "display_name": "Alice",
    "category": "PROFESSIONAL",
    "password": _RIGHT_PASSWORD,
}


@given(age=st.integers(min_value=-100, max_value=200))
@settings(max_examples=100, **_PBT_SETTINGS)
def test_property_2_age_range_bounds(age: int) -> None:
    """Property 2 (Req 1.4): UserCreate accepts age iff 15 <= age <= 100.

    Build a payload with every other field fixed to its valid baseline; the
    only thing that can move the validator's verdict is ``age``. Pydantic
    raises ``ValidationError`` on out-of-range values.
    """
    payload = {**_BASE_SIGNUP_PAYLOAD, "age": age}
    if 15 <= age <= 100:
        user = UserCreate(**payload)
        assert user.age == age
    else:
        with pytest.raises(ValidationError):
            UserCreate(**payload)


# --- Property 8: Session token validity window -----------------------------


@pytest.fixture(autouse=True)
def _set_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Login tests need ``JWT_SECRET`` set for ``encode_token``."""
    monkeypatch.setenv("JWT_SECRET", _TEST_JWT_SECRET)


@given(user_id=st.integers(min_value=1, max_value=10_000))
@settings(max_examples=20, **_PBT_SETTINGS)
def test_property_8_session_token_validity_window(user_id: int) -> None:
    """Property 8 (Req 3.1): JWT exp == iat + 24h, jti is fresh UUIDv4, no revoke.

    Drives ``AuthService.login`` against a mocked repo where
    ``get_by_email`` returns a User with the canonical password hash. We
    assert on the persisted session row's kwargs and on the JWT claim
    contents. ``revoked_at`` is the model default (None) — verified by the
    fact that the create_session call kwargs do not include it.

    bcrypt verify is real here so JWT issuance happens through the actual
    code path; ``max_examples=20`` keeps wall-clock budget tight.
    """
    service, user_repo, auth_repo, _ = _make_service()
    user_repo.get_by_email.return_value = _make_user(id=user_id)

    token, claims = service.login(email="alice@example.com", password=_RIGHT_PASSWORD)

    # JWT shape: header.payload.signature.
    assert isinstance(token, str)
    assert token.count(".") == 2

    # 24-hour validity window (Req 3.1).
    assert claims["exp"] - claims["iat"] == 24 * 3600

    # ``jti`` is a fresh UUIDv4.
    parsed = uuid.UUID(claims["jti"])
    assert parsed.version == 4

    # Persisted session row carries no ``revoked_at`` kwarg, so the column
    # falls through to its model default (NULL).
    auth_repo.create_session.assert_called_once()
    create_kwargs = auth_repo.create_session.call_args.kwargs
    assert "revoked_at" not in create_kwargs
    assert create_kwargs["jti"] == claims["jti"]
    assert create_kwargs["user_id"] == user_id

    # Persisted issued/expires match the claims (within the 1-second
    # rounding from int(timestamp())).
    issued_at = create_kwargs["issued_at"]
    expires_at = create_kwargs["expires_at"]
    assert isinstance(issued_at, datetime) and issued_at.tzinfo is not None
    assert isinstance(expires_at, datetime) and expires_at.tzinfo is not None
    assert int(issued_at.timestamp()) == claims["iat"]
    assert int(expires_at.timestamp()) == claims["exp"]


# --- Property 9: Login lockout ---------------------------------------------


@given(prior_failures=st.integers(min_value=0, max_value=10))
@settings(max_examples=100, **_PBT_SETTINGS)
def test_property_9_login_lockout_threshold(prior_failures: int) -> None:
    """Property 9 (Req 3.3): set_lockout called iff failed_count_in_window >= 5.

    The auth service records the failed attempt before counting, so the
    "count" the lockout decision reads against already includes the current
    failure. Mock ``failed_count_in_window`` to return ``prior_failures``,
    trigger a wrong-password login, and assert the lockout call shape.

    When the lock fires, ``locked_until`` is approximately ``now + 15min``
    (the service's default duration).
    """
    service, user_repo, auth_repo, _ = _make_service()
    user_repo.get_by_email.return_value = _make_user()
    auth_repo.failed_count_in_window.return_value = prior_failures

    before = datetime.now(tz=timezone.utc)
    with pytest.raises(HTTPException) as exc_info:
        service.login(email="alice@example.com", password="WrongPass1!")
    after = datetime.now(tz=timezone.utc)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "invalid_credentials"

    if prior_failures >= 5:
        auth_repo.set_lockout.assert_called_once()
        locked_until = auth_repo.set_lockout.call_args.kwargs["locked_until"]
        # ``locked_until ≈ now + 15min`` — bracket against the observed
        # before/after window so we don't depend on a single ``now`` call
        # inside the service.
        assert before + timedelta(minutes=14, seconds=59) <= locked_until
        assert locked_until <= after + timedelta(minutes=15, seconds=1)
    else:
        auth_repo.set_lockout.assert_not_called()


# --- Property 10: Forgot-password enumeration resistance ------------------


@given(
    email_exists=st.booleans(),
    # Random valid-shaped email so the email validator doesn't reject the
    # hypothesis input before we reach the service.
    local=st.text(
        alphabet=string.ascii_lowercase + string.digits + ".",
        min_size=1,
        max_size=16,
    ).filter(lambda s: not s.startswith(".") and not s.endswith(".")),
)
@settings(max_examples=100, **_PBT_SETTINGS)
def test_property_10_forgot_password_response_uniformity(
    email_exists: bool, local: str
) -> None:
    """Property 10 (Req 4.2): byte-equal response for existing/non-existing email.

    At the service layer the byte-equality reduces to a single rule: the
    method returns ``None`` and never raises, regardless of whether the
    email belonged to a real user. The byte-equal HTTP envelope is a
    router-level concern (Task 4.10) — that's where Property 10 gets its
    full test.

    We exercise both branches by toggling whether the mocked ``get_by_email``
    returns a user. When it does, the service must still return ``None`` and
    only ``otp_service.issue`` differs in being called.
    """
    service, user_repo, _, otp_service = _make_service()
    user = _make_user(email=f"{local}@example.com") if email_exists else None
    user_repo.get_by_email.return_value = user

    payload = PasswordResetRequest(email=f"{local}@example.com")
    result = service.request_password_reset(payload)

    # The contract: always returns None, never raises.
    assert result is None

    # The internal side effect (issue an OTP) only happens for known emails;
    # this is INVISIBLE to the caller and so doesn't break the property.
    if email_exists:
        otp_service.issue.assert_called_once()
    else:
        otp_service.issue.assert_not_called()


# --- Property 11: Password reset invalidates all sessions -----------------


@given(user_id=st.integers(min_value=1, max_value=10_000))
@settings(max_examples=20, **_PBT_SETTINGS)
def test_property_11_reset_revokes_all_sessions(user_id: int) -> None:
    """Property 11 (Req 4.4): reset_password revokes every prior session.

    After a successful reset, the service calls
    ``auth_repo.revoke_all_for_user(user_id)`` exactly once. The follow-on
    "subsequent token attempts return 401" is router-level (Task 4.10) and
    is documented but not asserted at the service layer.

    We mock ``otp_service.verify`` to return a User (as it would on a valid
    OTP) and drive ``reset_password`` through the success path.
    """
    service, user_repo, auth_repo, otp_service = _make_service()
    user = _make_user(id=user_id)
    otp_service.verify.return_value = user

    payload = PasswordResetConfirmRequest(
        email=user.email,
        code="123456",
        new_password="BrandNew2!Pass",
    )
    service.reset_password(payload)

    # Every session belonging to this user is revoked (Req 4.4).
    auth_repo.revoke_all_for_user.assert_called_once_with(user_id)

    # The user's password hash was updated; the new hash is bcrypt-shaped
    # and not equal to the plaintext.
    user_repo.update.assert_called_once()
    new_hash = user_repo.update.call_args.kwargs["password_hash"]
    assert isinstance(new_hash, str)
    assert new_hash.startswith("$2")
    assert new_hash != "BrandNew2!Pass"
