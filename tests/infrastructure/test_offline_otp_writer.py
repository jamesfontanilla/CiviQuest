"""Unit tests for ``OfflineOtpWriter``.

These tests cover Req 2.8: OTP delivery records are appended one JSON line
at a time to a local log file, the file is created with restrictive
permissions on POSIX, and writes are append-only and ordered.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from app.infrastructure.external.offline_otp_writer import OfflineOtpWriter


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def test_write_otp_creates_file_with_one_line(tmp_path: Path) -> None:
    log_path = tmp_path / "otp.log"
    writer = OfflineOtpWriter(log_path=str(log_path))

    writer.write_otp(email="user@example.com", purpose="VERIFY_EMAIL", code="123456")

    assert log_path.exists()
    contents = log_path.read_text(encoding="utf-8")
    assert contents.endswith("\n")
    lines = contents.splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert set(record.keys()) == {"timestamp", "email", "purpose", "code"}
    assert record["email"] == "user@example.com"
    assert record["purpose"] == "VERIFY_EMAIL"
    assert record["code"] == "123456"


def test_write_otp_is_append_only(tmp_path: Path) -> None:
    log_path = tmp_path / "otp.log"
    writer = OfflineOtpWriter(log_path=str(log_path))

    writer.write_otp(email="a@example.com", purpose="VERIFY_EMAIL", code="111111")
    writer.write_otp(email="b@example.com", purpose="VERIFY_EMAIL", code="222222")
    writer.write_otp(email="c@example.com", purpose="PASSWORD_RESET", code="333333")

    lines = _read_lines(log_path)
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert [r["email"] for r in parsed] == ["a@example.com", "b@example.com", "c@example.com"]
    assert [r["code"] for r in parsed] == ["111111", "222222", "333333"]


def test_write_otp_persists_plaintext_code_exactly_once_per_call(tmp_path: Path) -> None:
    log_path = tmp_path / "otp.log"
    writer = OfflineOtpWriter(log_path=str(log_path))
    code = "987654"

    writer.write_otp(email="user@example.com", purpose="VERIFY_EMAIL", code=code)

    contents = log_path.read_text(encoding="utf-8")
    assert contents.count(code) == 1


def test_write_otp_creates_parent_directory_if_missing(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "dir" / "otp.log"
    writer = OfflineOtpWriter(log_path=str(nested))

    writer.write_otp(email="user@example.com", purpose="VERIFY_EMAIL", code="123456")

    assert nested.exists()
    assert nested.parent.is_dir()


def test_write_otp_uses_iso8601_utc_timestamp(tmp_path: Path) -> None:
    log_path = tmp_path / "otp.log"
    writer = OfflineOtpWriter(log_path=str(log_path))

    writer.write_otp(email="user@example.com", purpose="VERIFY_EMAIL", code="123456")

    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    timestamp = record["timestamp"]
    # ``fromisoformat`` accepts both ``+00:00`` and ``Z`` on Python 3.11+,
    # but we want to be explicit that the suffix is UTC either way.
    assert timestamp.endswith("+00:00") or timestamp.endswith("Z")
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    assert parsed.utcoffset() is not None
    assert parsed.utcoffset().total_seconds() == 0


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX file mode bits are not enforced on Windows; ACLs are the right layer there.",
)
def test_write_otp_sets_owner_only_permissions(tmp_path: Path) -> None:
    log_path = tmp_path / "otp.log"
    writer = OfflineOtpWriter(log_path=str(log_path))

    writer.write_otp(email="user@example.com", purpose="VERIFY_EMAIL", code="123456")

    mode = os.stat(log_path).st_mode & 0o777
    assert oct(mode) == "0o600"


def test_health_check_returns_true_when_parent_writable(tmp_path: Path) -> None:
    log_path = tmp_path / "out.log"
    writer = OfflineOtpWriter(log_path=str(log_path))

    assert writer.health_check() is True
