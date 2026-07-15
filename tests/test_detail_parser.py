from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from bc_auction.errors import ParserContractError
from bc_auction.models import AuctionStatus, SearchResultRecord
from bc_auction.parsers import (
    parse_detail_summary_url,
    parse_detail_working_url,
    parse_item_detail,
    reconcile_search_result,
)

_FIXTURES = Path(__file__).parent / "fixtures"
_DETAIL_URL = "https://www.bcauction.ca/open.dll/showDocSummary?sessionID=SESSION_ID&disID=8733643"


def _detail() -> str:
    return (_FIXTURES / "item-detail.html").read_text()


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


def test_parses_captured_titleless_item_detail() -> None:
    detail = parse_item_detail(_detail(), _DETAIL_URL)

    assert detail.source_id == "A277437"
    assert detail.title == "Sanitized vehicle listing"
    assert detail.description == "Sanitized vehicle condition details."
    assert detail.category_raw == "Vehicles & Automotive"
    assert detail.location_raw == "Kelowna"
    assert detail.pickup_details == "Sanitized pickup details."
    assert detail.current_bid == Decimal("1000.00")
    assert detail.minimum_bid == Decimal("1025.00")
    assert detail.bid_count == 3
    assert detail.closing_at == datetime(2026, 7, 15, 18, 0, tzinfo=ZoneInfo("America/Vancouver"))
    assert detail.status_raw == "isbid=Y"
    assert detail.status == AuctionStatus.OPEN
    assert len(detail.image_urls) == 5
    assert str(detail.image_urls[0]) == "https://www.bcauction.ca/Pictures/8733643_Main.jpg"
    assert len(detail.content_hash) == 64


def test_reconciles_search_and_detail_values() -> None:
    detail = parse_item_detail(_detail(), _DETAIL_URL)
    search_result = SearchResultRecord(
        request_url=(
            "https://www.bcauction.ca/open.dll/showDisplayDocument?sessionID=SESSION_ID&disID=8733643"
        ),
        source_id="A277437",
        canonical_source_url="https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643",
        title=detail.title,
        location_raw=None,
        current_bid=Decimal("900.00"),
        closing_at=None,
        status=AuctionStatus.OPEN,
    )

    reconciled = reconcile_search_result(search_result, detail)

    assert reconciled.request_url == search_result.request_url
    assert reconciled.canonical_source_url == search_result.canonical_source_url
    assert reconciled.current_bid == Decimal("1000.00")
    assert reconciled.location_raw == "Kelowna"


def test_reconciles_same_auction_with_detail_title_authoritative() -> None:
    detail = parse_item_detail(_detail(), _DETAIL_URL)
    search_result = SearchResultRecord(
        request_url=(
            "https://www.bcauction.ca/open.dll/showDisplayDocument?sessionID=SESSION_ID&disID=8733643"
        ),
        source_id=detail.source_id,
        canonical_source_url="https://www.bcauction.ca/open.dll/showDisplayDocument?disID=8733643",
        title="Search title",
    )

    reconciled = reconcile_search_result(search_result, detail)

    assert reconciled.title == detail.title


def test_rejects_mismatched_search_and_detail_ids() -> None:
    detail = parse_item_detail(_detail(), _DETAIL_URL)
    search_result = SearchResultRecord(
        request_url="https://www.bcauction.ca/open.dll/showDisplayDocument?disID=1",
        source_id="A000001",
        canonical_source_url="https://www.bcauction.ca/open.dll/showDisplayDocument?disID=1",
        title=detail.title,
    )

    with pytest.raises(ParserContractError, match="different auction numbers"):
        reconcile_search_result(search_result, detail)


def test_rejects_cross_host_image_urls() -> None:
    html = _detail().replace("/Pictures/8733643_Main.jpg", "https://example.com/Pictures/item.jpg")

    with pytest.raises(ParserContractError, match="configured host"):
        parse_item_detail(html, _DETAIL_URL)


def test_deduplicates_image_urls_while_preserving_order() -> None:
    html = _detail().replace(
        '    <img src="/Pictures/8733643_Small4.jpg">',
        """    <img src="/Pictures/8733643_Small4.jpg">
    <img src="/Pictures/8733643_Main.jpg">
    <img src="https://www.bcauction.ca/Pictures/8733643_Small1.jpg">
    <img src="/Pictures/8733643_Small4.jpg">""",
    )

    detail = parse_item_detail(html, _DETAIL_URL)

    assert [str(image_url) for image_url in detail.image_urls] == [
        "https://www.bcauction.ca/Pictures/8733643_Main.jpg",
        "https://www.bcauction.ca/Pictures/8733643_Small1.jpg",
        "https://www.bcauction.ca/Pictures/8733643_Small2.jpg",
        "https://www.bcauction.ca/Pictures/8733643_Small3.jpg",
        "https://www.bcauction.ca/Pictures/8733643_Small4.jpg",
    ]


def test_strips_session_ids_from_image_urls_before_serialization() -> None:
    html = _detail().replace(
        "/Pictures/8733643_Main.jpg",
        "/Pictures/8733643_Main.jpg?sessionID=SECRET&size=large",
        1,
    )

    detail = parse_item_detail(html, _DETAIL_URL)

    assert str(detail.image_urls[0]).endswith("Pictures/8733643_Main.jpg?size=large")
    assert "SECRET" not in detail.model_dump_json()


def test_detail_hash_ignores_session_id_in_the_page_url() -> None:
    original = parse_item_detail(_detail(), _DETAIL_URL)
    changed_session = parse_item_detail(
        _detail(),
        _DETAIL_URL.replace("SESSION_ID", "DIFFERENT_SESSION"),
    )

    assert changed_session.content_hash == original.content_hash


def test_detail_hash_ignores_irrelevant_markup() -> None:
    html_with_navigation = _detail().replace(
        "<body>",
        "<body><nav>sessionID=DIFFERENT_SESSION navigation text</nav>",
    )

    original = parse_item_detail(_detail(), _DETAIL_URL)
    changed_markup = parse_item_detail(html_with_navigation, _DETAIL_URL)

    assert changed_markup.content_hash == original.content_hash


def test_detail_hash_changes_when_meaningful_auction_data_changes() -> None:
    original = parse_item_detail(_detail(), _DETAIL_URL)
    changed_bid = parse_item_detail(
        _detail().replace("1000.00<img", "1100.00<img"),
        _DETAIL_URL,
    )

    assert changed_bid.content_hash != original.content_hash


def test_rejects_a_detail_without_an_auction_number() -> None:
    html = _detail().replace("Auction Number:", "Auction Reference:")

    with pytest.raises(ParserContractError, match="auction number"):
        parse_item_detail(html, _DETAIL_URL)


def test_rejects_a_malformed_minimum_bid() -> None:
    html = _detail().replace('value="1025.00"', 'value="not-a-bid"')

    with pytest.raises(ParserContractError, match="minimum bid"):
        parse_item_detail(html, _DETAIL_URL)


def test_parses_detail_frame_navigation() -> None:
    frame_url = "https://www.bcauction.ca/open.dll/showDisplayDocument?sessionID=SESSION_ID"
    working_url = parse_detail_working_url(_fixture("item-detail-frame.html"), frame_url)
    summary_url = parse_detail_summary_url(_fixture("item-detail-working.html"), working_url)

    assert working_url.startswith("https://www.bcauction.ca/open.dll/showWorking?")
    assert summary_url == _DETAIL_URL


def test_rejects_cross_host_detail_summary_route() -> None:
    html = _fixture("item-detail-working.html").replace(
        "showDocSummary?",
        "https://example.com/open.dll/showDocSummary?",
    )

    with pytest.raises(ParserContractError, match="configured host"):
        parse_detail_summary_url(html, _DETAIL_URL)
