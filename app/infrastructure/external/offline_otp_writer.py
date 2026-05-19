"""Offline OTP delivery adapter.

Per Req 2.8, MVP delivers OTPs by appending a JSON line to a local log file
instead of sending email. This adapter owns that surface. The default path
is ``data/otp_offline.log`` (override via ``OTP_OFFLINE_LOG_PATH``).

Concurrency: APScheduler may run jobs concurrently with FastAPI request
threads, so writes are guarded by a module-level :class:`threading.Lock`
to keep lines from interleaving. The lock is process-local; the production
deployment is a single uvicorn process, so this is sufficient.

Permissions: on POSIX, the file is created with mode ``0o600`` (owner-only
read/write) because each line carries a plaintext OTP. On Windows the
``mode`` argument to ``os.open`` is largely ignored; filesystem ACLs are
the right enforcement layer there. We do not attempt to set Windows ACLs
from this adapter.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Final

from app.infrastructure.external.base import ExternalServiceBase

_DEFAULT_PATH: Final[str] = "data/otp_offline.log"

# Process-level lock — APScheduler workers and FastAPI threads share it.
_LOCK: Final[threading.Lock] = threading.Lock()


class OfflineOtpWriter(ExternalServiceBase):
    """Adapter that appends OTP delivery records to a local log file."""

    def __init__(self, log_path: str | None = None) -> None:
        if log_path is not None:
            self.log_path = log_path
        else:
            self.log_path = os.environ.get("OTP_OFFLINE_LOG_PATH", _DEFAULT_PATH)

    def write_otp(self, *, email: str, purpose: str, code: str) -> None:
        """Append one JSON line describing the OTP delivery.

        The line shape is::

            {"timestamp": "<ISO 8601 UTC>", "email": "...", "purpose": "...", "code": "..."}

        followed by ``\\n``. Timestamps use ``datetime.now(tz=timezone.utc)``;
        local time is intentionally avoided so the file is portable across
        the user's timezone changes.
        """
        record = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "email": email,
            "purpose": purpose,
            "code": code,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        self._ensure_parent_dir()
        # ``os.O_WRONLY | os.O_CREAT | os.O_APPEND`` with mode 0o600 keeps
        # the file owner-only on first creation. ``os.fdopen`` wraps the fd
        # so the rest of the call uses standard text-mode write semantics.
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        with _LOCK:
            fd = os.open(self.log_path, flags, 0o600)
            try:
                with os.fdopen(fd, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except BaseException:
                # ``os.fdopen`` takes ownership of the fd on success; if it
                # raises before that we must close it ourselves.
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise

    def _ensure_parent_dir(self) -> None:
        parent = os.path.dirname(self.log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def health_check(self) -> bool:
        """Return True iff the parent directory exists and is writable."""
        self._ensure_parent_dir()
        parent = os.path.dirname(self.log_path) or "."
        return os.access(parent, os.W_OK)
