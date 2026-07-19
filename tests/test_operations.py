from datetime import UTC, datetime

from bc_auction.operations import next_scheduled_at
from bc_auction.runtime import OperationsSettings


def test_next_scheduled_at_uses_pacific_schedule() -> None:
    settings = OperationsSettings(
        timezone="America/Vancouver",
        scrape_times=("06:00", "12:00", "18:00"),
        scrape_limit=1000,
        freshness_max_age_seconds=28800,
        maximum_run_seconds=7200,
    )

    next_run = next_scheduled_at(datetime(2026, 7, 19, 18, 30, tzinfo=UTC), settings)

    assert next_run == datetime(2026, 7, 19, 19, tzinfo=UTC)


def test_next_scheduled_at_rolls_to_tomorrow_after_last_run() -> None:
    settings = OperationsSettings(
        timezone="America/Vancouver",
        scrape_times=("06:00", "12:00", "18:00"),
        scrape_limit=1000,
        freshness_max_age_seconds=28800,
        maximum_run_seconds=7200,
    )

    next_run = next_scheduled_at(datetime(2026, 7, 20, 2, tzinfo=UTC), settings)

    assert next_run == datetime(2026, 7, 20, 13, tzinfo=UTC)
