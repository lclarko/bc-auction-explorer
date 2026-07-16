from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bc_auction.models import AuctionItem, SearchPagination, SearchResultRecord


def _item_data() -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "source_id": "A000001",
        "canonical_source_url": (
            "https://www.bcauction.ca/open.dll/showDisplayDocument?disID=1"
        ),
        "title": "Test item",
        "first_seen_at": now,
        "last_seen_at": now,
        "last_changed_at": now,
        "scraped_at": now,
        "raw_content_hash": "0" * 64,
        "parser_version": "results-v1",
    }


def test_item_accepts_aware_datetimes() -> None:
    item = AuctionItem.model_validate(_item_data())

    assert item.title == "Test item"


def test_item_rejects_naive_datetimes() -> None:
    data = _item_data()
    data["scraped_at"] = datetime.now()

    with pytest.raises(ValidationError):
        AuctionItem.model_validate(data)


def test_item_rejects_a_non_hex_content_hash() -> None:
    data = _item_data()
    data["raw_content_hash"] = "G" * 64

    with pytest.raises(ValidationError):
        AuctionItem.model_validate(data)


def test_item_rejects_session_bearing_request_urls() -> None:
    data = _item_data()
    data["request_url"] = "https://www.bcauction.ca/open.dll/item?sessionID=private"

    with pytest.raises(ValidationError):
        AuctionItem.model_validate(data)


def test_item_rejects_a_session_bearing_canonical_url() -> None:
    data = _item_data()
    data["canonical_source_url"] = (
        "https://www.bcauction.ca/open.dll/showDisplayDocument?sessionID=private&disID=1"
    )

    with pytest.raises(ValidationError, match="canonical source URL"):
        AuctionItem.model_validate(data)


def test_search_request_urls_are_not_serialized_or_represented() -> None:
    record = SearchResultRecord(
        source_id="A000001",
        canonical_source_url="https://www.bcauction.ca/open.dll/showDisplayDocument?disID=1",
        request_url="https://www.bcauction.ca/open.dll/showDisplayDocument?sessionID=private&disID=1",
        title="Test item",
    )
    pagination = SearchPagination(
        current_page=1,
        record_start=1,
        record_end=1,
        total_records=2,
        request_page_urls=(
            "https://www.bcauction.ca/open.dll/submitDocSearch?sessionID=private&currentPage=2",
        ),
        next_request_url=(
            "https://www.bcauction.ca/open.dll/submitDocSearch?sessionID=private&currentPage=2"
        ),
    )

    assert "private" not in repr(record)
    assert "request_url" not in record.model_dump()
    assert "private" not in pagination.model_dump_json()


def test_search_record_rejects_a_session_bearing_canonical_url() -> None:
    with pytest.raises(ValidationError, match="canonical source URL"):
        SearchResultRecord(
            source_id="A000001",
            canonical_source_url=(
                "https://www.bcauction.ca/open.dll/showDisplayDocument?sessionID=private&disID=1"
            ),
            request_url="https://www.bcauction.ca/open.dll/showDisplayDocument?sessionID=private&disID=1",
            title="Test item",
        )


def test_item_rejects_a_session_bearing_image_url() -> None:
    data = _item_data()
    data["image_urls"] = ("https://www.bcauction.ca/Pictures/item.jpg?sessionID=private",)

    with pytest.raises(ValidationError, match="image URLs"):
        AuctionItem.model_validate(data)
