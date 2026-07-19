"""Long-running operational scheduling for persisted public scrapes."""

from __future__ import annotations

import json
import logging
import signal
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from threading import Event
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.engine import Connection

from bc_auction.database import create_postgres_engine, resolve_database_url, scrape_runs
from bc_auction.runtime import OperationsSettings, configure_logging

_LOGGER = logging.getLogger("bc_auction.operations")
_LOCK_KEY = 884_220_611
_POLL_SECONDS = 1


def next_scheduled_at(now: datetime, settings: OperationsSettings) -> datetime:
    """Return the next configured local schedule point as a UTC timestamp."""

    local_now = now.astimezone(ZoneInfo(settings.timezone))
    candidates = []
    for time_text in settings.scrape_times:
        hour, minute = (int(part) for part in time_text.split(":"))
        candidates.append(local_now.replace(hour=hour, minute=minute, second=0, microsecond=0))
    future = [candidate for candidate in candidates if candidate > local_now]
    next_local = min(future) if future else min(candidates) + timedelta(days=1)
    return next_local.astimezone(UTC)


def has_complete_scrape(connection: Connection) -> bool:
    statement = select(scrape_runs.c.id).where(
        scrape_runs.c.status == "succeeded",
        scrape_runs.c.completion_status == "complete",
    )
    return connection.execute(statement.limit(1)).scalar_one_or_none() is not None


def try_advisory_lock(connection: Connection) -> bool:
    return bool(connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": _LOCK_KEY}))


def release_advisory_lock(connection: Connection) -> None:
    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK_KEY})


def _run_scrape(stop_requested: Event, settings: OperationsSettings) -> int:
    command = [
        sys.executable,
        "-m",
        "bc_auction",
        "scrape",
        "--persist",
        "--summary-only",
        "--run-mode",
        "scheduled",
        "--limit",
        str(settings.scrape_limit),
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    while process.poll() is None:
        if stop_requested.wait(_POLL_SECONDS):
            _LOGGER.info("scheduled_scrape_interrupted")
            process.terminate()
            try:
                return process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()
                return process.wait()
    stdout, stderr = process.communicate()
    _log_scrape_result(process.returncode, stdout, stderr)
    return process.returncode


def _log_scrape_result(return_code: int, stdout: str, stderr: str) -> None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        payload = {}
    summary = payload.get("summary") if isinstance(payload, dict) else None
    persistence = payload.get("persistence") if isinstance(payload, dict) else None
    _LOGGER.info(
        "scheduled_scrape_finished return_code=%s completion_status=%s "
        "record_count=%s failure_count=%s",
        return_code,
        persistence.get("completion_status") if isinstance(persistence, dict) else None,
        summary.get("record_count") if isinstance(summary, dict) else None,
        summary.get("failure_count") if isinstance(summary, dict) else None,
    )
    if stderr.strip():
        _LOGGER.warning("scheduled_scrape_stderr_present")


def main(argv: Sequence[str] | None = None) -> int:
    if argv:
        raise ValueError("operations service does not accept arguments")
    configure_logging()
    settings = OperationsSettings.from_environment()
    engine = create_postgres_engine(resolve_database_url())
    stop_requested = Event()

    def stop(_: int, __: object) -> None:
        stop_requested.set()

    previous_term = signal.signal(signal.SIGTERM, stop)
    previous_int = signal.signal(signal.SIGINT, stop)
    try:
        with engine.connect() as connection:
            initial_run_required = not has_complete_scrape(connection)
        _LOGGER.info("operations_started")
        while not stop_requested.is_set():
            if initial_run_required:
                due_at = datetime.now(UTC)
                initial_run_required = False
            else:
                due_at = next_scheduled_at(datetime.now(UTC), settings)
            wait_seconds = max(0, (due_at - datetime.now(UTC)).total_seconds())
            if stop_requested.wait(wait_seconds):
                break
            with engine.connect() as connection:
                if not try_advisory_lock(connection):
                    _LOGGER.warning("scheduled_scrape_skipped lock_held=true")
                    continue
                try:
                    _run_scrape(stop_requested, settings)
                finally:
                    release_advisory_lock(connection)
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
        engine.dispose()
        _LOGGER.info("operations_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
