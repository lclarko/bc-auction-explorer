"""Runtime configuration and structured application logging."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class RuntimeConfigurationError(ValueError):
    """Raised when non-secret production configuration is invalid."""


@dataclass(frozen=True, slots=True)
class RuntimeMetadata:
    version: str
    git_commit: str
    build_timestamp: str

    @classmethod
    def from_environment(cls) -> RuntimeMetadata:
        return cls(
            version=os.environ.get("BC_AUCTION_VERSION", "development"),
            git_commit=os.environ.get("BC_AUCTION_GIT_COMMIT", "unknown"),
            build_timestamp=os.environ.get("BC_AUCTION_BUILD_TIMESTAMP", "unknown"),
        )


@dataclass(frozen=True, slots=True)
class OperationsSettings:
    timezone: str
    scrape_times: tuple[str, ...]
    scrape_limit: int
    freshness_max_age_seconds: int
    maximum_run_seconds: int

    @classmethod
    def from_environment(cls) -> OperationsSettings:
        timezone = os.environ.get("BC_AUCTION_TIMEZONE", "America/Vancouver")
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise RuntimeConfigurationError("BC_AUCTION_TIMEZONE was invalid") from exc
        raw_times = os.environ.get("BC_AUCTION_SCRAPE_TIMES", "06:00,12:00,18:00")
        scrape_times = tuple(
            sorted({value.strip() for value in raw_times.split(",") if value.strip()})
        )
        if not scrape_times or any(not _is_clock_time(value) for value in scrape_times):
            raise RuntimeConfigurationError("BC_AUCTION_SCRAPE_TIMES must contain HH:MM values")
        return cls(
            timezone=timezone,
            scrape_times=scrape_times,
            scrape_limit=_positive_setting("BC_AUCTION_SCRAPE_LIMIT", 1000),
            freshness_max_age_seconds=_positive_setting(
                "BC_AUCTION_SCRAPE_FRESHNESS_MAX_AGE_SECONDS", 28800
            ),
            maximum_run_seconds=_positive_setting("BC_AUCTION_SCRAPE_MAX_RUN_SECONDS", 7200),
        )


def configure_logging() -> None:
    """Configure the application logger once with compact UTC JSON records."""

    logger = logging.getLogger("bc_auction")
    if logger.handlers:
        return
    level_name = os.environ.get("BC_AUCTION_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        raise RuntimeConfigurationError("BC_AUCTION_LOG_LEVEL was invalid")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
        }
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _positive_setting(name: str, default: int) -> int:
    raw_value = os.environ.get(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeConfigurationError(f"{name} must be an integer") from exc
    if value < 1:
        raise RuntimeConfigurationError(f"{name} must be positive")
    return value


def _is_clock_time(value: str) -> bool:
    if len(value) != 5 or value[2] != ":":
        return False
    try:
        hour = int(value[:2])
        minute = int(value[3:])
    except ValueError:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59
