"""Unit tests for security primitives: passwords, JWT, RNG.

Pure-function modules — no DB, no mocks. Tests here cover round-trip behavior,
explicit failure modes, and the configuration surface (cost factor, TTL).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import jwt as pyjwt  # disambiguate from the local `jwt` module name
import pytest

from app.infrastructure.security.jwt import (
    JWT_ALGORITHM,
    JWT_TTL_HOURS,
    decode_token,
    encode_token,
)
from app.infrastructure.security.passwords import BCRYPT_ROUNDS, hash_password, verify_password
from app.infrastructure.security.rng import randbelow_six_digits, sample, shuffle

# 32 bytes — meets the RFC 7518 §3.2 minimum for HS256 so pyjwt does not emit
# its InsecureKeyLengthWarning during the test run. Value is irrelevant.
_TEST_SECRET = "test-secret-please-ignore-32byte!!"


# --- bcrypt password hashing ---------------------------------------------------


def test_hash_password_round_trips() -> None:
    hashed = hash_password("CorrectHorse!1")
    assert verify_password("CorrectHorse!1", hashed) is True


def test_hash_password_rejects_wrong_password() -> None:
    hashed = hash_password("CorrectHorse!1")
    assert verify_password("WrongHorse!1", hashed) is False


def test_hash_password_uses_configured_cost_factor() -> None:
    hashed = hash_password("CorrectHorse!1")
    # bcrypt format: $2b$<cost>$<22-char salt><31-char hash>
    cost_segment = hashed.split("$")[2]
    assert cost_segment == f"{BCRYPT_ROUNDS:02d}"


def test_hash_password_does_not_return_plaintext() -> None:
    plaintext = "CorrectHorse!1"
    hashed = hash_password(plaintext)
    assert plaintext not in hashed


def test_hash_password_rejects_long_password() -> None:
    # 73 ASCII bytes > bcrypt's 72-byte input limit.
    too_long = "A" * 73
    with pytest.raises(ValueError):
        hash_password(too_long)


# --- JWT encode / decode -------------------------------------------------------


def test_encode_decode_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", _TEST_SECRET)
    token, claims = encode_token(sub="42")
    decoded = decode_token(token)

    assert decoded["sub"] == "42"
    assert decoded["jti"] == claims["jti"]
    assert decoded["iat"] == claims["iat"]
    assert decoded["exp"] == claims["exp"]
    assert decoded["exp"] - decoded["iat"] == JWT_TTL_HOURS * 3600


def test_encode_generates_unique_jtis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", _TEST_SECRET)
    _, claims_a = encode_token(sub="42")
    _, claims_b = encode_token(sub="42")
    assert claims_a["jti"] != claims_b["jti"]


def test_decode_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", _TEST_SECRET)
    past = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    iat = int((past - timedelta(hours=JWT_TTL_HOURS)).timestamp())
    exp = int(past.timestamp())
    expired = pyjwt.encode(
        {"sub": "42", "jti": "fixed-jti", "iat": iat, "exp": exp},
        _TEST_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_token(expired)


def test_decode_rejects_tampered_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", _TEST_SECRET)
    token, _ = encode_token(sub="42")
    header, payload, signature = token.split(".")
    # Flip a character in the signature segment. Pick one guaranteed to land
    # on something different so the result is genuinely tampered.
    flipped_char = "A" if signature[0] != "A" else "B"
    tampered = f"{header}.{payload}.{flipped_char}{signature[1:]}"
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_token(tampered)


def test_encode_raises_when_secret_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        encode_token(sub="1")


# --- RNG sanity ----------------------------------------------------------------


def test_randbelow_six_digits_returns_zero_padded_string() -> None:
    pattern = re.compile(r"^\d{6}$")
    for _ in range(200):
        code = randbelow_six_digits()
        assert pattern.fullmatch(code) is not None


def test_sample_returns_distinct_subset() -> None:
    population = list(range(50))
    chosen = sample(population, 10)
    assert len(chosen) == 10
    assert len(set(chosen)) == 10
    assert all(0 <= x < 50 for x in chosen)


def test_shuffle_mutates_in_place() -> None:
    original = list(range(20))
    seq = list(original)
    # SystemRandom.shuffle of 20 distinct elements producing the identity
    # permutation has probability 1/20!. Re-shuffle a few times to drive the
    # flake probability to functionally zero while still failing loudly if
    # shuffle is a no-op.
    for _ in range(5):
        shuffle(seq)
        if seq != original:
            break
    assert seq != original
    assert sorted(seq) == original
