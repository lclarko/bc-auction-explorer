import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect, select

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
    ScrapeRunCounts,
    ScrapeRunInput,
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


@pytest.fixture
def repository() -> AuctionRepository:
    database_url = os.environ.get("BC_AUCTION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("BC_AUCTION_TEST_DATABASE_URL is not configured")
    if not database_url.rsplit("/", maxsplit=1)[-1].startswith("bc_auction_test"):
        pytest.fail(
            "BC_AUCTION_TEST_DATABASE_URL must target an isolated bc_auction_test database"
        )

    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_postgres_engine(database_url)
    try:
        yield AuctionRepository(engine)
    finally:
        engine.dispose()


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

    assert changed.updated is True
    assert changed.observation_created is True
    with repository._engine.connect() as connection:
        item = connection.execute(select(auction_items)).mappings().one()
        assert item["title"] == "Updated utility vehicle"
        assert item["last_changed_at"] == datetime(2026, 7, 15, 1, tzinfo=UTC)
        assert len(connection.execute(select(item_observations)).all()) == 2


def test_closed_listings_remain_queryable_and_identity_collisions_fail(
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

    conflicting = convert_reconciled_record(
        _detail(source_id="A000002"),
        observed_at=datetime(2026, 7, 15, 1, tzinfo=UTC),
    )
    with pytest.raises(IdentityConflictError):
        repository.persist_reconciled_record(run_id, conflicting)


def test_partial_and_failed_run_statuses_are_queryable(repository: AuctionRepository) -> None:
    run_id = _run(repository)
    counts = ScrapeRunCounts(
        pages_visited=1,
        items_seen=2,
        items_created=1,
        items_updated=0,
        observations_created=1,
        item_failures=1,
    )
    repository.finish_scrape_run(run_id, status=ScrapeRunStatus.PARTIAL, counts=counts)

    with repository._engine.connect() as connection:
        row = connection.execute(
            select(scrape_runs.c.status, scrape_runs.c.item_failures).where(
                scrape_runs.c.id == run_id
            )
        ).one()
    assert row == (ScrapeRunStatus.PARTIAL.value, 1)
