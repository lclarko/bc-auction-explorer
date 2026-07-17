from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from bc_auction.models import AuctionDetailRecord, AuctionStatus, LocationStatus
from bc_auction.persistence import PersistedAuctionRecord, convert_reconciled_record


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
        "description": "Sanitized details",
        "category_raw": "Vehicles",
        "location_raw": "Victoria - Uvic",
        "pickup_details": "By appointment",
        "current_bid": Decimal("25.00"),
        "minimum_bid": Decimal("10.00"),
        "bid_count": 2,
        "closing_at": datetime(2026, 7, 16, 10, tzinfo=UTC),
        "status_raw": "isbid=Y",
        "status": AuctionStatus.OPEN,
        "image_urls": ("https://www.bcauction.ca/Pictures/8733643.jpg",),
        "content_hash": "0" * 64,
    }
    data.update(updates)
    return AuctionDetailRecord.model_validate(data)


def test_conversion_preserves_public_data_and_excludes_request_values() -> None:
    persisted = convert_reconciled_record(_detail(), observed_at=datetime(2026, 7, 15, tzinfo=UTC))

    assert persisted.source_dis_id == "8733643"
    assert persisted.location_canonical == "Victoria"
    assert persisted.location_qualifier == "UVic"
    assert persisted.location_normalization_status is LocationStatus.ALIAS
    assert persisted.category_canonical is None
    assert persisted.starting_bid is None
    assert "request_url" not in persisted.model_dump()
    assert "private" not in persisted.model_dump_json()


def test_hashes_ignore_observed_at_but_distinguish_missing_and_zero_values() -> None:
    first = convert_reconciled_record(_detail(), observed_at=datetime(2026, 7, 15, tzinfo=UTC))
    repeated = convert_reconciled_record(
        _detail(),
        observed_at=datetime(2026, 7, 15, tzinfo=UTC) + timedelta(minutes=5),
    )
    missing_bid = convert_reconciled_record(
        _detail(current_bid=None),
        observed_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    zero_bid = convert_reconciled_record(
        _detail(current_bid=Decimal("0.00")),
        observed_at=datetime(2026, 7, 15, tzinfo=UTC),
    )

    assert first.metadata_hash == repeated.metadata_hash
    assert first.observation_hash == repeated.observation_hash
    assert missing_bid.observation_hash != zero_bid.observation_hash


def test_conversion_retains_unknown_locations_without_guessing() -> None:
    persisted = convert_reconciled_record(
        _detail(location_raw="Qualicum Beach"),
        observed_at=datetime(2026, 7, 15, tzinfo=UTC),
    )

    assert persisted.location_canonical == "Qualicum Beach"
    assert persisted.location_normalization_status is LocationStatus.UNKNOWN


def test_persistence_record_rejects_mutated_or_session_bearing_canonical_identity() -> None:
    persisted = convert_reconciled_record(_detail(), observed_at=datetime(2026, 7, 15, tzinfo=UTC))
    mismatched_display_id = persisted.model_dump()
    mismatched_display_id["source_dis_id"] = "9999999"
    session_bearing_url = persisted.model_dump()
    session_bearing_url["canonical_source_url"] = (
        "https://www.bcauction.ca/open.dll/showDisplayDocument?"
        "disID=8733643&sessionID=private"
    )

    with pytest.raises(ValidationError, match="display ID"):
        PersistedAuctionRecord.model_validate(mismatched_display_id)
    with pytest.raises(ValidationError, match="canonical source URL"):
        PersistedAuctionRecord.model_validate(session_bearing_url)


def test_detail_record_rejects_credential_bearing_image_url() -> None:
    with pytest.raises(ValidationError, match="embedded credentials"):
        _detail(image_urls=("https://user:secret@www.bcauction.ca/Pictures/8733643.jpg",))
