from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from alembic import command
from bc_auction.database import (
    auction_items,
    create_postgres_engine,
    item_observations,
    scrape_runs,
)
from bc_auction.models import AuctionDetailRecord, AuctionStatus
from bc_auction.persistence import (
    AuctionRepository,
    IdentityConflictError,
    PersistenceError,
    ScrapeRunCounts,
    ScrapeRunInput,
    ScrapeRunMetrics,
    ScrapeRunStatus,
    convert_reconciled_record,
)

pytestmark = pytest.mark.integration


def _detail(**updates: object) -> AuctionDetailRecord:
    data: dict[str, object] = {
        "source_id": "A000001",
        "canonical_source_url": (
            "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643"
        ),
        "request_url": (
            "https://www.bcauction.ca/open.dll/showDocSummary?sessionID=private&disID=8733643"
        ),
        "title": "Utility vehicle",
        "location_raw": "Victoria",
        "current_bid": Decimal("25.00"),
        "minimum_bid": Decimal("10.00"),
        "bid_count": 2,
        "closing_at": datetime(2026, 7, 16, 10, tzinfo=UTC),
        "status_raw": "isbid=Y",
        "status": AuctionStatus.OPEN,
        "content_hash": "0" * 64,
    }
    data.update(updates)
    return AuctionDetailRecord.model_validate(data)


def _run(repository: AuctionRepository) -> object:
    return repository.start_scrape_run(
        ScrapeRunInput(
            requested_limit=1,
            keyword="",
            sort="EndingFirst",
            parser_version="test-v1",
        ),
        started_at=datetime(2026, 7, 15, tzinfo=UTC),
    )


def test_migration_creates_the_persistence_schema(repository: AuctionRepository) -> None:
    engine = repository._engine
    assert {"scrape_runs", "auction_items", "item_observations", "location_aliases"} <= set(
        inspect(engine).get_table_names()
    )
    assert "current_observation_hash" in {
        column["name"] for column in inspect(engine).get_columns("auction_items")
    }
    assert "uq_item_observations_item_observed_hash" in {
        constraint["name"]
        for constraint in inspect(engine).get_unique_constraints("item_observations")
    }


def test_repeat_ingestion_is_idempotent_and_preserves_history(
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    initial = convert_reconciled_record(_detail(), observed_at=datetime(2026, 7, 15, tzinfo=UTC))
    repeated = convert_reconciled_record(
        _detail(),
        observed_at=datetime(2026, 7, 15, tzinfo=UTC) + timedelta(minutes=10),
    )

    assert repository.persist_reconciled_record(run_id, initial).created is True
    result = repository.persist_reconciled_record(run_id, repeated)

    assert result.created is False
    assert result.updated is False
    assert result.observation_created is False
    with repository._engine.connect() as connection:
        assert len(connection.execute(select(auction_items)).all()) == 1
        assert len(connection.execute(select(item_observations)).all()) == 1


def test_current_observation_hash_migration_uses_the_latest_scrape_run(
    repository: AuctionRepository,
) -> None:
    first_run_id = repository.start_scrape_run(
        ScrapeRunInput(
            requested_limit=1,
            keyword="",
            sort="EndingFirst",
            parser_version="test-v1",
        ),
        started_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    observed_at = datetime(2026, 7, 15, 1, tzinfo=UTC)
    repository.persist_reconciled_record(
        first_run_id,
        convert_reconciled_record(_detail(current_bid=Decimal("25.00")), observed_at=observed_at),
    )
    latest_run_id = repository.start_scrape_run(
        ScrapeRunInput(
            requested_limit=1,
            keyword="",
            sort="EndingFirst",
            parser_version="test-v1",
        ),
        started_at=datetime(2026, 7, 15, 0, 1, tzinfo=UTC),
    )
    latest_record = convert_reconciled_record(
        _detail(current_bid=Decimal("30.00")),
        observed_at=observed_at,
    )
    repository.persist_reconciled_record(latest_run_id, latest_record)

    database_url = repository._engine.url.render_as_string(hide_password=False)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    repository._engine.dispose()
    command.downgrade(config, "20260716_02")
    try:
        command.upgrade(config, "20260716_03")
        engine = create_postgres_engine(database_url)
        try:
            with engine.connect() as connection:
                item = connection.execute(select(auction_items)).mappings().one()
        finally:
            engine.dispose()
        assert item["current_observation_hash"] == latest_record.observation_hash
    finally:
        command.upgrade(config, "head")


def test_current_observation_hash_migration_preserves_terminal_snapshot(
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    closed_record = convert_reconciled_record(
        _detail(
            current_bid=Decimal("30.00"),
            status=AuctionStatus.CLOSED,
            status_raw="Closed",
            title="Closed utility vehicle",
        ),
        observed_at=datetime(2026, 7, 15, 1, tzinfo=UTC),
    )
    repository.persist_reconciled_record(run_id, closed_record)
    newer_open_record = convert_reconciled_record(
        _detail(
            current_bid=Decimal("35.00"),
            title="Transient open utility vehicle",
        ),
        observed_at=datetime(2026, 7, 15, 2, tzinfo=UTC),
    )
    repository.persist_reconciled_record(run_id, newer_open_record)

    database_url = repository._engine.url.render_as_string(hide_password=False)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    repository._engine.dispose()
    command.downgrade(config, "20260716_02")
    try:
        command.upgrade(config, "20260716_03")
        engine = create_postgres_engine(database_url)
        try:
            with engine.connect() as connection:
                item = connection.execute(select(auction_items)).mappings().one()
        finally:
            engine.dispose()
        assert item["status"] == AuctionStatus.CLOSED.value
        assert item["current_observation_hash"] == closed_record.observation_hash
        assert item["current_observation_hash"] != newer_open_record.observation_hash
    finally:
        command.upgrade(config, "head")


def test_current_observation_hash_migration_preserves_open_snapshot(
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    open_record = convert_reconciled_record(
        _detail(
            current_bid=Decimal("30.00"),
            title="Open utility vehicle",
        ),
        observed_at=datetime(2026, 7, 15, 1, tzinfo=UTC),
    )
    repository.persist_reconciled_record(run_id, open_record)
    newer_closed_record = convert_reconciled_record(
        _detail(
            current_bid=Decimal("35.00"),
            status=AuctionStatus.CLOSED,
            status_raw="Closed",
            title="Transient closed utility vehicle",
        ),
        observed_at=datetime(2026, 7, 15, 2, tzinfo=UTC),
    )
    repository.persist_reconciled_record(run_id, newer_closed_record)

    database_url = repository._engine.url.render_as_string(hide_password=False)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    repository._engine.dispose()
    command.downgrade(config, "20260716_02")
    legacy_engine = create_postgres_engine(database_url)
    try:
        with legacy_engine.begin() as connection:
            connection.execute(
                update(auction_items)
                .where(auction_items.c.source_id == open_record.source_id)
                .values(
                    status=AuctionStatus.OPEN.value,
                    closed_at=None,
                )
            )
    finally:
        legacy_engine.dispose()
    try:
        command.upgrade(config, "20260716_03")
        engine = create_postgres_engine(database_url)
        try:
            with engine.connect() as connection:
                item = connection.execute(select(auction_items)).mappings().one()
        finally:
            engine.dispose()
        assert item["status"] == AuctionStatus.OPEN.value
        assert item["current_observation_hash"] == open_record.observation_hash
        assert item["current_observation_hash"] != newer_closed_record.observation_hash
    finally:
        command.upgrade(config, "head")


def test_current_observation_hash_migration_rejects_ambiguous_history(
    repository: AuctionRepository,
) -> None:
    observed_at = datetime(2026, 7, 15, 1, tzinfo=UTC)
    first_run_id = _run(repository)
    repository.persist_reconciled_record(
        first_run_id,
        convert_reconciled_record(_detail(current_bid=Decimal("25.00")), observed_at=observed_at),
    )
    second_run_id = _run(repository)
    repository.persist_reconciled_record(
        second_run_id,
        convert_reconciled_record(_detail(current_bid=Decimal("30.00")), observed_at=observed_at),
    )

    database_url = repository._engine.url.render_as_string(hide_password=False)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    repository._engine.dispose()
    command.downgrade(config, "20260716_02")
    try:
        with pytest.raises(DBAPIError, match="ambiguous current observation history"):
            command.upgrade(config, "20260716_03")
    finally:
        command.downgrade(config, "base")


def test_observation_and_metadata_changes_update_the_current_item(
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    repository.persist_reconciled_record(
        run_id,
        convert_reconciled_record(_detail(), observed_at=datetime(2026, 7, 15, tzinfo=UTC)),
    )
    changed = repository.persist_reconciled_record(
        run_id,
        convert_reconciled_record(
            _detail(current_bid=Decimal("30.00"), title="Updated utility vehicle"),
            observed_at=datetime(2026, 7, 15, 1, tzinfo=UTC),
        ),
    )
    stale = repository.persist_reconciled_record(
        run_id,
        convert_reconciled_record(
            _detail(current_bid=Decimal("20.00"), title="Stale utility vehicle"),
            observed_at=datetime(2026, 7, 15, 0, 30, tzinfo=UTC),
        ),
    )
    repeated_stale = repository.persist_reconciled_record(
        run_id,
        convert_reconciled_record(
            _detail(current_bid=Decimal("20.00"), title="Stale utility vehicle"),
            observed_at=datetime(2026, 7, 15, 0, 30, tzinfo=UTC),
        ),
    )
    unchanged_current_record = convert_reconciled_record(
        _detail(current_bid=Decimal("30.00"), title="Updated utility vehicle"),
        observed_at=datetime(2026, 7, 15, 2, tzinfo=UTC),
    )
    unchanged_current = repository.persist_reconciled_record(run_id, unchanged_current_record)

    assert changed.updated is True
    assert changed.observation_created is True
    assert stale.updated is False
    assert stale.observation_created is True
    assert repeated_stale.observation_created is False
    assert unchanged_current.updated is False
    assert unchanged_current.observation_created is False
    with repository._engine.connect() as connection:
        item = connection.execute(select(auction_items)).mappings().one()
        assert item["title"] == "Updated utility vehicle"
        assert item["last_changed_at"] == datetime(2026, 7, 15, 1, tzinfo=UTC)
        assert item["last_seen_at"] == datetime(2026, 7, 15, 2, tzinfo=UTC)
        assert item["current_observation_hash"] == unchanged_current_record.observation_hash
        assert len(connection.execute(select(item_observations)).all()) == 3


def test_stale_terminal_observation_does_not_change_the_current_item(
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    current_record = convert_reconciled_record(
        _detail(),
        observed_at=datetime(2026, 7, 15, 2, tzinfo=UTC),
    )
    repository.persist_reconciled_record(run_id, current_record)

    stale_terminal_record = convert_reconciled_record(
        _detail(status=AuctionStatus.CLOSED, status_raw="Closed"),
        observed_at=datetime(2026, 7, 15, 1, tzinfo=UTC),
    )
    stale_terminal = repository.persist_reconciled_record(run_id, stale_terminal_record)
    repeated_stale_terminal = repository.persist_reconciled_record(
        run_id,
        stale_terminal_record,
    )

    assert stale_terminal.updated is False
    assert stale_terminal.observation_created is True
    assert repeated_stale_terminal.updated is False
    assert repeated_stale_terminal.observation_created is False
    with repository._engine.connect() as connection:
        item = connection.execute(select(auction_items)).mappings().one()
    assert item["status"] == AuctionStatus.OPEN.value
    assert item["closed_at"] is None
    assert item["last_seen_at"] == datetime(2026, 7, 15, 2, tzinfo=UTC)
    assert item["last_changed_at"] == datetime(2026, 7, 15, 2, tzinfo=UTC)
    assert item["current_observation_hash"] == current_record.observation_hash


def test_terminal_snapshot_is_not_reopened_by_a_newer_nonterminal_observation(
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    closed_record = convert_reconciled_record(
        _detail(
            current_bid=Decimal("30.00"),
            status=AuctionStatus.CLOSED,
            status_raw="Closed",
            title="Closed utility vehicle",
        ),
        observed_at=datetime(2026, 7, 15, 1, tzinfo=UTC),
    )
    repository.persist_reconciled_record(run_id, closed_record)
    reopened_record = convert_reconciled_record(
        _detail(
            current_bid=Decimal("35.00"),
            status=AuctionStatus.OPEN,
            status_raw="isbid=Y",
            title="Transient open utility vehicle",
        ),
        observed_at=datetime(2026, 7, 15, 2, tzinfo=UTC),
    )

    reopened = repository.persist_reconciled_record(run_id, reopened_record)
    repeated_reopened = repository.persist_reconciled_record(
        run_id,
        reopened_record.model_copy(update={"observed_at": datetime(2026, 7, 15, 3, tzinfo=UTC)}),
    )

    assert reopened.updated is False
    assert reopened.observation_created is True
    assert repeated_reopened.updated is False
    assert repeated_reopened.observation_created is False
    with repository._engine.connect() as connection:
        item = connection.execute(select(auction_items)).mappings().one()
        observations = connection.execute(select(item_observations)).all()
    assert item["title"] == "Closed utility vehicle"
    assert item["status"] == AuctionStatus.CLOSED.value
    assert item["closed_at"] == datetime(2026, 7, 15, 1, tzinfo=UTC)
    assert item["last_seen_at"] == datetime(2026, 7, 15, 3, tzinfo=UTC)
    assert item["last_changed_at"] == datetime(2026, 7, 15, 1, tzinfo=UTC)
    assert item["current_observation_hash"] == closed_record.observation_hash
    assert len(observations) == 2


def test_closed_listings_remain_queryable_and_cross_listing_identity_collisions_fail(
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    closed = convert_reconciled_record(
        _detail(status=AuctionStatus.CLOSED, status_raw="Closed"),
        observed_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    repository.persist_reconciled_record(run_id, closed)

    with repository._engine.connect() as connection:
        item = connection.execute(select(auction_items)).mappings().one()
        assert item["status"] == AuctionStatus.CLOSED.value
        assert item["closed_at"] == datetime(2026, 7, 15, tzinfo=UTC)

    stale_closed = repository.persist_reconciled_record(
        run_id,
        convert_reconciled_record(
            _detail(status=AuctionStatus.CLOSED, status_raw="Closed"),
            observed_at=datetime(2026, 7, 14, 23, tzinfo=UTC),
        ),
    )
    assert stale_closed.updated is False
    assert stale_closed.observation_created is True
    with repository._engine.connect() as connection:
        item = connection.execute(select(auction_items)).mappings().one()
    assert item["closed_at"] == datetime(2026, 7, 15, tzinfo=UTC)

    conflicting = convert_reconciled_record(
        _detail(source_id="A000002"),
        observed_at=datetime(2026, 7, 15, 1, tzinfo=UTC),
    )
    with pytest.raises(IdentityConflictError):
        repository.persist_reconciled_record(run_id, conflicting)

    with repository._engine.connect() as connection:
        item = connection.execute(select(auction_items)).mappings().one()
    assert item["source_dis_id"] == "8733643"


def test_same_source_id_can_remap_to_a_new_public_document_and_preserve_history(
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    initial = convert_reconciled_record(
        _detail(),
        observed_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    remapped = convert_reconciled_record(
        _detail(
            canonical_source_url=(
                "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8734000"
            )
        ),
        observed_at=datetime(2026, 7, 15, 2, tzinfo=UTC),
    )

    assert repository.persist_reconciled_record(run_id, initial).created is True
    result = repository.persist_reconciled_record(run_id, remapped)

    assert result.created is False
    assert result.updated is True
    assert result.observation_created is False

    with repository._engine.connect() as connection:
        item = connection.execute(select(auction_items)).mappings().one()
        observations = connection.execute(select(item_observations)).all()
    assert item["source_id"] == "A000001"
    assert item["source_dis_id"] == "8734000"
    assert item["canonical_source_url"] == (
        "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8734000"
    )
    assert item["first_seen_at"] == datetime(2026, 7, 15, tzinfo=UTC)
    assert item["last_seen_at"] == datetime(2026, 7, 15, 2, tzinfo=UTC)
    assert item["last_changed_at"] == datetime(2026, 7, 15, 2, tzinfo=UTC)
    assert len(observations) == 1


def test_repository_revalidates_session_free_trusted_remap_urls(
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    initial = convert_reconciled_record(
        _detail(),
        observed_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    repository.persist_reconciled_record(run_id, initial)

    session_bearing_remap = initial.model_copy(
        update={
            "source_dis_id": "8734000",
            "canonical_source_url": (
                "https://www.bcauction.ca/open.dll/showDisplayDocument?"
                "disID=8734000&sessionID=private"
            ),
        }
    )
    external_remap = initial.model_copy(
        update={
            "source_dis_id": "8734001",
            "canonical_source_url": "https://example.com/open.dll/showDisplayDocument?disID=8734001",
        }
    )

    with pytest.raises(PersistenceError, match="failed validation") as session_error:
        repository.persist_reconciled_record(run_id, session_bearing_remap)
    assert "sessionID" not in str(session_error.value)
    assert "private" not in str(session_error.value)
    with pytest.raises(PersistenceError, match="failed validation"):
        repository.persist_reconciled_record(run_id, external_remap)

    with repository._engine.connect() as connection:
        item = connection.execute(select(auction_items)).mappings().one()
        observations = connection.execute(select(item_observations)).all()
    assert item["source_dis_id"] == "8733643"
    assert item["canonical_source_url"] == (
        "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643"
    )
    assert len(observations) == 1


def test_repository_recomputes_hashes_for_a_copied_record(
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    initial = convert_reconciled_record(
        _detail(),
        observed_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    copied_with_changed_fields = initial.model_copy(
        update={
            "title": "Updated utility vehicle",
            "current_bid": Decimal("30.00"),
            "observed_at": datetime(2026, 7, 15, 1, tzinfo=UTC),
        }
    )

    repository.persist_reconciled_record(run_id, initial)
    result = repository.persist_reconciled_record(run_id, copied_with_changed_fields)

    assert result.updated is True
    assert result.observation_created is True
    with repository._engine.connect() as connection:
        item = connection.execute(select(auction_items)).mappings().one()
        observations = connection.execute(select(item_observations)).all()
    assert item["title"] == "Updated utility vehicle"
    assert len(observations) == 2


def test_document_remap_does_not_reopen_a_terminal_item(
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    closed = convert_reconciled_record(
        _detail(status=AuctionStatus.CLOSED, status_raw="Closed"),
        observed_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    remapped_open = convert_reconciled_record(
        _detail(
            canonical_source_url=(
                "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8734000"
            )
        ),
        observed_at=datetime(2026, 7, 15, 1, tzinfo=UTC),
    )

    repository.persist_reconciled_record(run_id, closed)
    result = repository.persist_reconciled_record(run_id, remapped_open)

    assert result.updated is True
    assert result.observation_created is True
    with repository._engine.connect() as connection:
        item = connection.execute(select(auction_items)).mappings().one()
        observations = connection.execute(select(item_observations)).all()
    assert item["status"] == AuctionStatus.CLOSED.value
    assert item["source_dis_id"] == "8734000"
    assert item["canonical_source_url"] == (
        "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8734000"
    )
    assert item["last_changed_at"] == datetime(2026, 7, 15, 1, tzinfo=UTC)
    assert len(observations) == 2


def test_scrape_run_lifecycle_is_enforced(repository: AuctionRepository) -> None:
    run_id = _run(repository)
    counts = ScrapeRunCounts(
        pages_visited=1,
        items_seen=2,
        items_created=1,
        items_updated=0,
        observations_created=1,
        item_failures=1,
    )
    with pytest.raises(ValueError, match="cannot be finalized"):
        repository.finish_scrape_run(run_id, status=ScrapeRunStatus.RUNNING, counts=counts)
    metrics = ScrapeRunMetrics(
        source_requests=12,
        source_responses=11,
        source_retries=2,
        rate_limit_responses=1,
        source_transport_errors=1,
        source_request_duration_ms=3210,
        source_request_wait_duration_ms=4500,
        source_retry_wait_duration_ms=1000,
    )
    repository.finish_scrape_run(
        run_id,
        status=ScrapeRunStatus.PARTIAL,
        counts=counts,
        metrics=metrics,
    )

    with repository._engine.connect() as connection:
        row = connection.execute(
            select(
                scrape_runs.c.status,
                scrape_runs.c.item_failures,
                scrape_runs.c.source_requests,
                scrape_runs.c.source_responses,
                scrape_runs.c.source_retries,
                scrape_runs.c.rate_limit_responses,
                scrape_runs.c.source_transport_errors,
                scrape_runs.c.source_request_duration_ms,
                scrape_runs.c.source_request_wait_duration_ms,
                scrape_runs.c.source_retry_wait_duration_ms,
            ).where(scrape_runs.c.id == run_id)
        ).one()
    assert row == (ScrapeRunStatus.PARTIAL.value, 1, 12, 11, 2, 1, 1, 3210, 4500, 1000)

    failed_run_id = _run(repository)
    repository.finish_scrape_run(
        failed_run_id,
        status=ScrapeRunStatus.FAILED,
        counts=counts,
        error_summary="scrape failed",
    )
    with repository._engine.connect() as connection:
        failed_row = connection.execute(
            select(
                scrape_runs.c.status,
                scrape_runs.c.finished_at,
                scrape_runs.c.error_summary,
                scrape_runs.c.items_created,
                scrape_runs.c.observations_created,
            ).where(scrape_runs.c.id == failed_run_id)
        ).one()
    assert failed_row.status == ScrapeRunStatus.FAILED.value
    assert failed_row.finished_at is not None
    assert failed_row.error_summary == "scrape failed"
    assert failed_row.items_created == 1
    assert failed_row.observations_created == 1

    constraint_run_id = _run(repository)
    with pytest.raises(IntegrityError):
        with repository._engine.begin() as connection:
            connection.execute(
                update(scrape_runs)
                .where(scrape_runs.c.id == constraint_run_id)
                .values(finished_at=datetime(2026, 7, 15, 1, tzinfo=UTC))
            )


@pytest.mark.parametrize(
    "column_name",
    (
        "source_requests",
        "source_responses",
        "source_retries",
        "rate_limit_responses",
        "source_transport_errors",
        "source_request_duration_ms",
        "source_request_wait_duration_ms",
        "source_retry_wait_duration_ms",
    ),
)
def test_scrape_run_metrics_reject_negative_values(
    repository: AuctionRepository,
    column_name: str,
) -> None:
    run_id = _run(repository)

    with pytest.raises(IntegrityError):
        with repository._engine.begin() as connection:
            connection.execute(
                update(scrape_runs)
                .where(scrape_runs.c.id == run_id)
                .values({column_name: -1})
            )
