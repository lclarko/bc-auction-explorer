from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bc_auction.models import AuctionItem


def _item_data() -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "source_url": "https://www.bcauction.ca/open.dll/item",
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
