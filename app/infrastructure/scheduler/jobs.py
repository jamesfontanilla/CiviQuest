"""APScheduler jobs for OTP cleanup and offline-log rotation.

Two jobs are registered:

* ``cleanup_expired_otps`` — hourly. Deletes ``otps`` rows whose
  ``expires_at`` is more than 24h in the past. Wrapped in try/except so a
  transient DB error does not crash the scheduler thread.
* ``rotate_offline_otp_log`` — daily at 00:05 UTC. Rotates the offline OTP
  log to ``<path>.<yesterday>.gz`` and truncates the original.

The scheduler is a process-wide singleton; ``start_scheduler`` and
``stop_scheduler`` are idempotent so they can be safely called from the
FastAPI lifespan even if the test runner imports and tears down the app
multiple times.

Test isolation: setting ``DISABLE_SCHEDULER=1`` in the environment makes
``start_scheduler`` a no-op. The test suite sets this in ``conftest.py``
via an autouse session fixture so unit tests do not spin up timers.
"""

from __future__ import annotations

import gzip
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_OFFLINE_LOG_PATH_DEFAULT = "data/otp_offline.log"
_OTP_RETENTION_HOURS = 24

_scheduler: BackgroundScheduler | None = None


def _offline_log_path() -> str:
    return os.environ.get("OTP_OFFLINE_LOG_PATH", _OFFLINE_LOG_PATH_DEFAULT)


def cleanup_expired_otps() -> None:
    """Delete OTP rows with ``expires_at`` older than 24h.

    Imports happen inside the function so the scheduler's module-level
    import doesn't pull the entire app graph in (and because the
    ``SessionLocal`` factory needs the production engine, which is
    constructed lazily on first import).
    """
    from sqlalchemy import delete

    from app.features.otp.models import OTP
    from app.infrastructure.database.session import SessionLocal

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=_OTP_RETENTION_HOURS)
    session = SessionLocal()
    try:
        try:
            session.execute(delete(OTP).where(OTP.expires_at < cutoff))
            session.commit()
        except Exception:  # noqa: BLE001 — never let a DB error kill the job.
            session.rollback()
            logger.exception("cleanup_expired_otps failed")
    finally:
        session.close()


def rotate_offline_otp_log() -> None:
    """Rotate the offline OTP log to ``<path>.<yesterday>.gz`` and truncate.

    Runs daily at 00:05 UTC. If the file does not exist or is empty, the
    function returns without rotating. The "yesterday" date is computed in
    UTC so rotation does not drift across the user's local timezone.
    """
    path = _offline_log_path()
    try:
        if not os.path.exists(path):
            return
        if os.path.getsize(path) == 0:
            return
        yesterday = (datetime.now(tz=timezone.utc).date() - timedelta(days=1)).isoformat()
        rotated = f"{path}.{yesterday}.gz"
        # gzip-write a copy of the current contents, then truncate the
        # original. Truncating in place keeps the same inode and preserves
        # the 0o600 mode on POSIX.
        with open(path, "rb") as src, gzip.open(rotated, "wb") as dst:
            shutil.copyfileobj(src, dst)
        with open(path, "w", encoding="utf-8") as fh:
            fh.truncate(0)
    except Exception:  # noqa: BLE001 — log and swallow so the scheduler stays up.
        logger.exception("rotate_offline_otp_log failed")


def start_scheduler() -> BackgroundScheduler | None:
    """Start (or return) the singleton scheduler.

    Idempotent: a second call returns the already-running scheduler. When
    ``DISABLE_SCHEDULER=1`` is set in the environment, the function is a
    no-op and returns ``None``; the test suite uses this to keep timers
    out of unit tests.
    """
    if os.environ.get("DISABLE_SCHEDULER") == "1":
        return None

    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="UTC")
        _scheduler.add_job(
            cleanup_expired_otps,
            trigger=IntervalTrigger(hours=1),
            id="cleanup_expired_otps",
            replace_existing=True,
        )
        _scheduler.add_job(
            rotate_offline_otp_log,
            trigger=CronTrigger(hour=0, minute=5, timezone="UTC"),
            id="rotate_offline_otp_log",
            replace_existing=True,
        )
    _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    """Stop the singleton scheduler if running. Idempotent."""
    global _scheduler
    if _scheduler is None:
        return
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
