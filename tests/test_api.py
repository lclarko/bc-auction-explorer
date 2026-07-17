from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from bc_auction.api import create_app
from bc_auction.models import AuctionDetailRecord, AuctionStatus
from bc_auction.persistence import (
    AuctionRepository,
    ScrapeRunCounts,
    ScrapeRunInput,
    ScrapeRunStatus,
    convert_reconciled_record,
)
from bc_auction.read_repository import AuctionReadRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def client(repository: AuctionRepository) -> Iterator[TestClient]:
    with TestClient(
        create_app(engine=repository._engine),
        raise_server_exceptions=False,
    ) as api_client:
        yield api_client


def _detail(
    source_id: str,
    display_id: str,
    *,
    title: str,
    current_bid: Decimal | None,
    closing_at: datetime | None,
    location: str = "Victoria",
    category: str = "Vehicles",
    status: AuctionStatus = AuctionStatus.OPEN,
    bid_count: int | None = 2,
    image_urls: tuple[str, ...] = (),
) -> AuctionDetailRecord:
    return AuctionDetailRecord.model_validate(
        {
            "source_id": source_id,
            "canonical_source_url": (
                "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=" f"{display_id}"
            ),
            "request_url": (
                "https://www.bcauction.ca/open.dll/showDocSummary?sessionID=private&disID="
                f"{display_id}"
            ),
            "title": title,
            "description": f"Description for {title}",
            "category_raw": category,
            "location_raw": location,
            "pickup_details": "Weekdays by appointment",
            "current_bid": current_bid,
            "minimum_bid": Decimal("10.00"),
            "bid_count": bid_count,
            "closing_at": closing_at,
            "status_raw": "Closed" if status is AuctionStatus.CLOSED else "isbid=Y",
            "status": status,
            "image_urls": image_urls,
            "content_hash": "0" * 64,
        }
    )


def _run(repository: AuctionRepository) -> object:
    return repository.start_scrape_run(
        ScrapeRunInput(
            requested_limit=3,
            keyword="",
            sort="EndingFirst",
            parser_version="test-v1",
        ),
        started_at=datetime(2026, 7, 16, tzinfo=UTC),
    )


def _finish(repository: AuctionRepository, run_id: object) -> None:
    repository.finish_scrape_run(
        run_id,
        status=ScrapeRunStatus.SUCCEEDED,
        counts=ScrapeRunCounts(
            pages_visited=1,
            items_seen=3,
            items_created=3,
            items_updated=0,
            observations_created=3,
            item_failures=0,
        ),
        finished_at=datetime(2026, 7, 16, 1, tzinfo=UTC),
    )


def _persist(
    repository: AuctionRepository,
    run_id: object,
    detail: AuctionDetailRecord,
    *,
    observed_at: datetime,
) -> None:
    repository.persist_reconciled_record(
        run_id,
        convert_reconciled_record(detail, observed_at=observed_at),
    )


def test_listings_filter_sort_and_paginate(
    client: TestClient,
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    _persist(
        repository,
        run_id,
        _detail(
            "A000001",
            "8733641",
            title="Utility vehicle",
            current_bid=Decimal("25.00"),
            closing_at=datetime(2026, 7, 17, 10, tzinfo=UTC),
        ),
        observed_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    _persist(
        repository,
        run_id,
        _detail(
            "A000002",
            "8733642",
            title="Utility trailer",
            current_bid=Decimal("30.00"),
            closing_at=datetime(2026, 7, 16, 10, tzinfo=UTC),
            image_urls=("https://www.bcauction.ca/images/utility-trailer.jpg",),
        ),
        observed_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    _persist(
        repository,
        run_id,
        _detail(
            "A000003",
            "8733643",
            title="Office desk",
            current_bid=Decimal("15.00"),
            closing_at=datetime(2026, 7, 18, 10, tzinfo=UTC),
            location="Kelowna",
            category="Office furniture",
        ),
        observed_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    _finish(repository, run_id)

    listing_params = {
        "keyword": "utility",
        "location": "victoria",
        "category": "vehicles",
        "status": "open",
        "min_price": "20",
        "max_price": "30",
        "closing_after": "2026-07-16T00:00:00Z",
        "closing_before": "2026-07-17T23:59:59Z",
        "sort": "price_high",
        "page_size": 1,
    }
    response = client.get("/api/listings", params=listing_params)

    assert response.status_code == 200
    payload = response.json()
    assert payload["page_info"] == {
        "page": 1,
        "page_size": 1,
        "total_items": 2,
        "total_pages": 2,
    }
    assert [item["source_id"] for item in payload["items"]] == ["A000002"]
    assert Decimal(payload["items"][0]["current_bid"]) == Decimal("30.00")
    assert payload["items"][0]["canonical_source_url"] == (
        "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733642"
    )
    assert payload["items"][0]["image_urls"] == [
        "https://www.bcauction.ca/images/utility-trailer.jpg"
    ]
    assert "request_url" not in payload["items"][0]
    assert "metadata_hash" not in payload["items"][0]
    assert "sessionID" not in payload["items"][0]["canonical_source_url"]
    assert "sessionID" not in payload["items"][0]["image_urls"][0]

    second_page = client.get(
        "/api/listings",
        params={**listing_params, "page": 2},
    )
    assert second_page.status_code == 200
    assert [item["source_id"] for item in second_page.json()["items"]] == ["A000001"]


def test_listing_detail_preserves_terminal_current_snapshot(
    client: TestClient,
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    closed = _detail(
        "A000001",
        "8733641",
        title="Closed utility vehicle",
        current_bid=Decimal("30.00"),
        closing_at=datetime(2026, 7, 16, 10, tzinfo=UTC),
        status=AuctionStatus.CLOSED,
    )
    _persist(
        repository,
        run_id,
        closed,
        observed_at=datetime(2026, 7, 16, 1, tzinfo=UTC),
    )
    newer_open = _detail(
        "A000001",
        "8733641",
        title="Transient open utility vehicle",
        current_bid=Decimal("35.00"),
        closing_at=datetime(2026, 7, 16, 11, tzinfo=UTC),
    )
    _persist(
        repository,
        run_id,
        newer_open,
        observed_at=datetime(2026, 7, 16, 2, tzinfo=UTC),
    )
    _finish(repository, run_id)

    response = client.get("/api/listings/A000001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "closed"
    assert Decimal(payload["current_bid"]) == Decimal("30.00")
    assert payload["title"] == "Closed utility vehicle"
    assert payload["description"] == "Description for Closed utility vehicle"
    assert payload["closed_at"] is not None
    assert "source_dis_id" not in payload
    assert "current_observation_hash" not in payload


def test_listing_sorts_are_deterministic_and_put_nulls_last(
    client: TestClient,
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    records = (
        (
            "A000001",
            "8733641",
            Decimal("20.00"),
            datetime(2026, 7, 17, 10, tzinfo=UTC),
            5,
            datetime(2026, 7, 16, 1, tzinfo=UTC),
        ),
        (
            "A000002",
            "8733642",
            Decimal("20.00"),
            datetime(2026, 7, 16, 10, tzinfo=UTC),
            5,
            datetime(2026, 7, 16, 2, tzinfo=UTC),
        ),
        (
            "A000003",
            "8733643",
            Decimal("10.00"),
            datetime(2026, 7, 18, 10, tzinfo=UTC),
            2,
            datetime(2026, 7, 16, 3, tzinfo=UTC),
        ),
        (
            "A000004",
            "8733644",
            None,
            None,
            None,
            datetime(2026, 7, 16, 4, tzinfo=UTC),
        ),
    )
    for source_id, display_id, bid, closing_at, bid_count, observed_at in records:
        _persist(
            repository,
            run_id,
            _detail(
                source_id,
                display_id,
                title=f"Listing {source_id}",
                current_bid=bid,
                closing_at=closing_at,
                bid_count=bid_count,
            ),
            observed_at=observed_at,
        )
    _finish(repository, run_id)

    expected_orders = {
        "closing_soon": ["A000002", "A000001", "A000003", "A000004"],
        "closing_latest": ["A000003", "A000001", "A000002", "A000004"],
        "price_low": ["A000003", "A000001", "A000002", "A000004"],
        "price_high": ["A000001", "A000002", "A000003", "A000004"],
        "newest_seen": ["A000004", "A000003", "A000002", "A000001"],
        "most_bids": ["A000001", "A000002", "A000003", "A000004"],
    }
    for sort, expected_source_ids in expected_orders.items():
        response = client.get("/api/listings", params={"sort": sort, "page_size": 10})
        assert response.status_code == 200
        assert [item["source_id"] for item in response.json()["items"]] == expected_source_ids


def test_facets_and_scrape_status_exclude_persistence_details(
    client: TestClient,
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    _persist(
        repository,
        run_id,
        _detail(
            "A000001",
            "8733641",
            title="Utility vehicle",
            current_bid=Decimal("25.00"),
            closing_at=datetime(2026, 7, 17, 10, tzinfo=UTC),
        ),
        observed_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    _persist(
        repository,
        run_id,
        _detail(
            "A000002",
            "8733642",
            title="Office desk",
            current_bid=Decimal("15.00"),
            closing_at=datetime(2026, 7, 18, 10, tzinfo=UTC),
            location="Kelowna",
            category="Office furniture",
        ),
        observed_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    _finish(repository, run_id)
    repository.start_scrape_run(
        ScrapeRunInput(
            requested_limit=3,
            keyword="",
            sort="EndingFirst",
            parser_version="test-v1",
        ),
        started_at=datetime(2026, 7, 16, 2, tzinfo=UTC),
    )

    locations = client.get("/api/locations")
    categories = client.get("/api/categories")
    status = client.get("/api/scrape-status")

    assert locations.status_code == 200
    assert locations.json()["items"] == [
        {"value": "Kelowna", "count": 1},
        {"value": "Victoria", "count": 1},
    ]
    assert categories.status_code == 200
    assert categories.json()["items"] == [
        {"value": "Office furniture", "count": 1},
        {"value": "Vehicles", "count": 1},
    ]
    assert status.status_code == 200
    status_payload = status.json()
    assert status_payload["listing_count"] == 2
    assert status_payload["latest_run"]["status"] == "running"
    assert status_payload["latest_successful_run"]["status"] == "succeeded"
    assert status_payload["latest_listing_seen_at"].endswith("Z")
    assert "id" not in status_payload["latest_run"]
    assert "error_summary" not in status_payload["latest_run"]


def test_api_returns_stable_errors_without_database_details(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = client.get("/api/listings/does-not-exist")
    unknown_route = client.get("/api/does-not-exist")
    method_not_allowed = client.post("/api/listings")
    invalid_price_range = client.get("/api/listings?min_price=20&max_price=10")
    invalid_timestamp = client.get("/api/listings?closing_after=2026-07-16T12:00:00")
    invalid_page_size = client.get("/api/listings?page_size=101")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "listing_not_found"
    assert unknown_route.status_code == 404
    assert unknown_route.json()["error"]["code"] == "request_error"
    assert method_not_allowed.status_code == 405
    assert method_not_allowed.json()["error"]["code"] == "request_error"
    assert invalid_price_range.status_code == 422
    assert invalid_price_range.json()["error"]["code"] == "invalid_filter"
    assert invalid_timestamp.status_code == 422
    assert invalid_timestamp.json()["error"]["code"] == "invalid_filter"
    assert invalid_page_size.status_code == 422
    assert invalid_page_size.json()["error"]["code"] == "validation_error"
    assert "input" not in invalid_page_size.json()["error"]["details"][0]

    def unavailable(_: AuctionReadRepository, __: object) -> object:
        raise OperationalError("SELECT 1", {}, RuntimeError("database details"))

    monkeypatch.setattr(AuctionReadRepository, "list_listings", unavailable)
    unavailable_response = client.get("/api/listings")

    assert unavailable_response.status_code == 503
    assert unavailable_response.json()["error"] == {
        "code": "database_unavailable",
        "message": "Database is temporarily unavailable",
        "details": None,
    }


@pytest.mark.parametrize("parameter", ("min_price", "max_price"))
def test_api_rejects_price_filter_outside_storage_range(
    client: TestClient,
    parameter: str,
) -> None:
    response = client.get("/api/listings", params={parameter: "1000000000000"})

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert "input" not in payload["error"]["details"][0]
