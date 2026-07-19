from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from bc_auction.api import create_app
from bc_auction.models import AuctionDetailRecord, AuctionStatus
from bc_auction.persistence import (
    AuctionRepository,
    ScrapeRunCounts,
    ScrapeRunCoverage,
    ScrapeRunInput,
    ScrapeRunMetrics,
    ScrapeRunStatus,
    convert_reconciled_record,
)
from bc_auction.read_repository import AuctionReadRepository

pytestmark = pytest.mark.integration
_REQUEST_TIME = datetime(2026, 7, 16, 12, tzinfo=UTC)


def _test_now() -> datetime:
    return _REQUEST_TIME


@pytest.fixture
def client(repository: AuctionRepository) -> Iterator[TestClient]:
    with TestClient(
        create_app(engine=repository._engine, now_provider=_test_now),
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


def _finish(
    repository: AuctionRepository,
    run_id: object,
    *,
    metrics: ScrapeRunMetrics | None = None,
) -> None:
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
        metrics=metrics,
        coverage=ScrapeRunCoverage(
            expected_product_groups=1,
            processed_product_groups=1,
            unique_listings_enumerated=3,
            detail_attempted=3,
            detail_succeeded=3,
            persistence_succeeded=3,
            enumeration_complete=True,
        ),
        finished_at=datetime(2026, 7, 16, 1, tzinfo=UTC),
    )


def test_health_endpoints_report_database_and_operations_state(
    client: TestClient,
    repository: AuctionRepository,
) -> None:
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ok"}

    initial_operations = client.get("/health/operations")
    assert initial_operations.status_code == 200
    assert initial_operations.json()["state"] == "starting"

    run_id = _run(repository)
    _persist(
        repository,
        run_id,
        _detail(
            "A000001",
            "8733641",
            title="Operations listing",
            current_bid=Decimal("25.00"),
            closing_at=datetime(2026, 7, 17, 10, tzinfo=UTC),
        ),
        observed_at=_REQUEST_TIME,
    )
    _finish(repository, run_id)

    operations = client.get("/health/operations")
    assert operations.status_code == 200
    assert operations.json()["state"] == "healthy"
    assert operations.json()["latest_complete_run"]["run_id"]


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
        "min_price": "20",
        "max_price": "30",
        "closing_after": "2026-07-15T17:00:00-07:00",
        "closing_before": "2026-07-17T16:59:59-07:00",
        "view": "all",
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
    assert payload["items"][0]["availability"] == "scheduled_closing_passed"
    assert payload["items"][0]["observed_at"] == "2026-07-16T00:00:00Z"
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
    assert payload["availability"] == "closed"
    assert Decimal(payload["current_bid"]) == Decimal("30.00")
    assert payload["title"] == "Closed utility vehicle"
    assert payload["description"] == "Description for Closed utility vehicle"
    assert payload["closed_at"] is not None
    assert payload["observed_at"] == "2026-07-16T01:00:00Z"
    assert "source_dis_id" not in payload
    assert "current_observation_hash" not in payload

    ended = client.get("/api/listings", params={"view": "ended", "page_size": 10})

    assert ended.status_code == 200
    ended_item = ended.json()["items"][0]
    assert ended.json()["page_info"]["total_items"] == 1
    assert ended_item["availability"] == "closed"
    assert Decimal(ended_item["current_bid"]) == Decimal("30.00")
    assert ended_item["observed_at"] == "2026-07-16T01:00:00Z"
    assert ended_item["status"] == "closed"
    assert ended_item["title"] == "Closed utility vehicle"


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
        response = client.get(
            "/api/listings",
            params={"view": "all", "sort": sort, "page_size": 10},
        )
        assert response.status_code == 200
        assert [item["source_id"] for item in response.json()["items"]] == expected_source_ids


def test_listing_views_scope_current_observations_facets_and_availability(
    repository: AuctionRepository,
) -> None:
    run_id = _run(repository)
    observed_at = _REQUEST_TIME - timedelta(hours=2)
    records = (
        (
            "A000001",
            "8733641",
            "Future open listing",
            _REQUEST_TIME + timedelta(hours=1),
            "Active City",
            "Active category",
            AuctionStatus.OPEN,
        ),
        (
            "A000002",
            "8733642",
            "Open listing without a closing time",
            None,
            "No deadline City",
            "No deadline category",
            AuctionStatus.OPEN,
        ),
        (
            "A000003",
            "8733643",
            "Open listing closing now",
            _REQUEST_TIME,
            "Scheduled City",
            "Scheduled category",
            AuctionStatus.OPEN,
        ),
        (
            "A000004",
            "8733644",
            "Open listing with a passed closing time",
            _REQUEST_TIME - timedelta(hours=1),
            "Passed City",
            "Passed category",
            AuctionStatus.OPEN,
        ),
        (
            "A000005",
            "8733645",
            "Closed listing with a future closing time",
            _REQUEST_TIME + timedelta(hours=2),
            "Closed City",
            "Closed category",
            AuctionStatus.CLOSED,
        ),
        (
            "A000006",
            "8733646",
            "Withdrawn listing without a closing time",
            None,
            "Withdrawn City",
            "Withdrawn category",
            AuctionStatus.WITHDRAWN,
        ),
        (
            "A000007",
            "8733647",
            "Unknown source status listing",
            _REQUEST_TIME + timedelta(hours=3),
            "Unknown City",
            "Unknown category",
            AuctionStatus.UNKNOWN,
        ),
    )
    for source_id, display_id, title, closing_at, location, category, status in records:
        _persist(
            repository,
            run_id,
            _detail(
                source_id,
                display_id,
                title=title,
                current_bid=Decimal("20.00"),
                closing_at=closing_at,
                location=location,
                category=category,
                status=status,
            ),
            observed_at=observed_at,
        )
    _finish(repository, run_id)

    calls = 0

    def now_provider() -> datetime:
        nonlocal calls
        calls += 1
        return _REQUEST_TIME

    with TestClient(
        create_app(engine=repository._engine, now_provider=now_provider),
        raise_server_exceptions=False,
    ) as api_client:
        active = api_client.get("/api/listings", params={"page_size": 10})
        assert calls == 1
        ended = api_client.get("/api/listings", params={"view": "ended", "page_size": 10})
        assert calls == 2
        ended_closing_soon = api_client.get(
            "/api/listings",
            params={"view": "ended", "sort": "closing_soon", "page_size": 10},
        )
        assert calls == 3
        all_listings = api_client.get("/api/listings", params={"view": "all", "page_size": 10})
        assert calls == 4
        active_locations = api_client.get("/api/locations")
        assert calls == 5
        ended_categories = api_client.get("/api/categories", params={"view": "ended"})
        assert calls == 6
        unknown_detail = api_client.get("/api/listings/A000007")
        assert calls == 7

    assert active.status_code == 200
    active_payload = active.json()
    assert active_payload["page_info"]["total_items"] == 2
    assert [item["source_id"] for item in active_payload["items"]] == ["A000001", "A000002"]
    assert [item["availability"] for item in active_payload["items"]] == ["active", "unknown"]
    assert active_payload["items"][0]["observed_at"] == "2026-07-16T10:00:00Z"

    assert ended.status_code == 200
    ended_payload = ended.json()
    assert ended_payload["page_info"]["total_items"] == 4
    assert [item["source_id"] for item in ended_payload["items"]] == [
        "A000005",
        "A000003",
        "A000004",
        "A000006",
    ]
    assert [item["availability"] for item in ended_payload["items"]] == [
        "closed",
        "scheduled_closing_passed",
        "scheduled_closing_passed",
        "withdrawn",
    ]
    passed_open = next(item for item in ended_payload["items"] if item["source_id"] == "A000004")
    assert passed_open["status"] == "open"
    assert passed_open["closed_at"] is None

    assert ended_closing_soon.status_code == 200
    assert [item["source_id"] for item in ended_closing_soon.json()["items"]] == [
        "A000004",
        "A000003",
        "A000005",
        "A000006",
    ]

    assert all_listings.status_code == 200
    all_payload = all_listings.json()
    assert all_payload["page_info"]["total_items"] == 7
    assert [item["source_id"] for item in all_payload["items"]] == [
        "A000004",
        "A000003",
        "A000001",
        "A000005",
        "A000007",
        "A000002",
        "A000006",
    ]
    assert all_payload["items"][4]["availability"] == "unknown"

    assert active_locations.status_code == 200
    assert active_locations.json()["items"] == [
        {"value": "Active City", "count": 1},
        {"value": "No deadline City", "count": 1},
    ]
    assert ended_categories.status_code == 200
    assert ended_categories.json()["items"] == [
        {"value": "Closed category", "count": 1},
        {"value": "Passed category", "count": 1},
        {"value": "Scheduled category", "count": 1},
        {"value": "Withdrawn category", "count": 1},
    ]

    assert unknown_detail.status_code == 200
    assert unknown_detail.json()["availability"] == "unknown"
    assert unknown_detail.json()["observed_at"] == "2026-07-16T10:00:00Z"


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
    metrics = ScrapeRunMetrics(
        source_requests=11,
        source_responses=12,
        source_retries=13,
        rate_limit_responses=14,
        source_transport_errors=15,
        source_request_duration_ms=16,
        source_request_wait_duration_ms=17,
        source_retry_wait_duration_ms=18,
    )
    _finish(repository, run_id, metrics=metrics)
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
    assert {
        field: status_payload["latest_successful_run"][field] for field in asdict(metrics)
    } == asdict(metrics)
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

    def unavailable(
        _: AuctionReadRepository,
        __: object,
        *,
        request_time: datetime,
    ) -> object:
        raise OperationalError("SELECT 1", {}, RuntimeError("database details"))

    monkeypatch.setattr(AuctionReadRepository, "list_listings", unavailable)
    unavailable_response = client.get("/api/listings")

    assert unavailable_response.status_code == 503
    assert unavailable_response.json()["error"] == {
        "code": "database_unavailable",
        "message": "Database is temporarily unavailable",
        "details": None,
    }


@pytest.mark.parametrize("parameter", ["min_price", "max_price"])
def test_api_rejects_price_filter_outside_storage_range(
    client: TestClient,
    parameter: str,
) -> None:
    response = client.get("/api/listings", params={parameter: "1000000000000"})

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert "input" not in payload["error"]["details"][0]


@pytest.mark.parametrize("parameter", ["min_price", "max_price"])
def test_api_accepts_largest_persistable_price_filter(
    client: TestClient,
    parameter: str,
) -> None:
    response = client.get("/api/listings", params={parameter: "999999999999.99"})

    assert response.status_code == 200
