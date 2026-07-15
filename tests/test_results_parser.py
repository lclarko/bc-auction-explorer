from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest

from bc_auction.errors import ParserContractError
from bc_auction.models import AuctionStatus
from bc_auction.parsers import SearchPageTracker, parse_search_results

_FIXTURES = Path(__file__).parent / "fixtures"
_RESULTS_URL = "https://www.bcauction.ca/open.dll/submitDocSearch"


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def test_parses_captured_open_results_page() -> None:
    page = parse_search_results(_fixture("results-open-page-1.html"), _RESULTS_URL)

    assert len(page.records) == 30
    assert page.pagination is not None
    assert page.pagination.current_page == 1
    assert page.pagination.record_start == 1
    assert page.pagination.record_end == 30
    assert page.pagination.total_records == 131
    assert len(page.pagination.request_page_urls) == 4
    assert page.pagination.next_request_url is not None
    assert parse_qs(urlparse(str(page.pagination.next_request_url)).query)["currentPage"] == ["2"]

    first = page.records[0]
    assert first.source_id == "A277437"
    assert first.title == "Sanitized listing 001"
    assert first.location_raw == "Kelowna"
    assert first.current_bid == Decimal("100.00")
    assert first.minimum_bid is None
    assert first.bid_count is None
    assert first.closing_at == datetime(2026, 7, 15, 18, 0, tzinfo=ZoneInfo("America/Vancouver"))
    assert first.status_raw == "OpenDocument0.gif"
    assert first.status == AuctionStatus.OPEN
    assert str(first.request_url).startswith("https://www.bcauction.ca/open.dll/showDisplayDocument?")
    assert "sessionID=SESSION_ID" in str(first.request_url)
    assert "sessionID" not in str(first.canonical_source_url)
    assert "disID=8733643" in str(first.canonical_source_url)
    assert "SESSION_ID" not in page.model_dump_json()


def test_parses_next_page_and_highest_price_sort() -> None:
    second_page = parse_search_results(_fixture("results-open-page-2.html"), _RESULTS_URL)
    highest_price = parse_search_results(_fixture("results-open-highest-price.html"), _RESULTS_URL)

    assert second_page.pagination is not None
    assert second_page.pagination.current_page == 2
    assert second_page.pagination.record_start == 31
    assert second_page.records[0].source_id == "A277450"

    assert highest_price.pagination is not None
    assert highest_price.records[0].current_bid == Decimal("900.00")
    assert highest_price.pagination.next_request_url is not None
    query = parse_qs(urlparse(str(highest_price.pagination.next_request_url)).query)
    assert query["display_order"] == ["HighestPrice"]


def test_parses_captured_empty_results_page() -> None:
    page = parse_search_results(_fixture("results-empty.html"), _RESULTS_URL)

    assert page.records == ()
    assert page.pagination is None


def test_parses_closed_results_without_a_listing_title() -> None:
    page = parse_search_results(_fixture("results-closed.html"), _RESULTS_URL)

    assert len(page.records) == 1
    record = page.records[0]
    assert record.source_id == "A000001"
    assert record.title is None
    assert record.current_bid == Decimal("125.00")
    assert record.bid_count == 3
    assert record.status == AuctionStatus.CLOSED
    assert record.status_raw == "ClosedDocSearch1.gif"
    assert str(record.canonical_source_url).endswith("showDisplayDocument?disID=999")


def test_recognizes_the_withdrawn_result_icon() -> None:
    html = _fixture("results-closed.html").replace(
        "ClosedDocSearch1.gif",
        "closed_withdrawn.gif",
    )

    page = parse_search_results(html, _RESULTS_URL)

    assert page.records[0].status == AuctionStatus.WITHDRAWN


def test_rejects_markup_without_results_or_the_empty_marker() -> None:
    html = """
    <html><head><title>Browse Auctions</title></head>
    <body><form action="submitDocSearch"></form></body></html>
    """

    with pytest.raises(ParserContractError, match="recognized heading set"):
        parse_search_results(html, _RESULTS_URL)


def test_rejects_duplicate_source_ids() -> None:
    html = _fixture("results-open-page-1.html").replace("A277501", "A277437")

    with pytest.raises(ParserContractError, match="duplicate source IDs"):
        parse_search_results(html, _RESULTS_URL)


def test_rejects_cross_host_detail_urls() -> None:
    html = _fixture("results-open-page-1.html").replace(
        "https://www.bcauction.ca/open.dll/showDisplayDocument",
        "https://example.com/open.dll/showDisplayDocument",
        1,
    )

    with pytest.raises(ParserContractError, match="configured host"):
        parse_search_results(html, _RESULTS_URL)


@pytest.mark.parametrize(
    ("replacement", "replace_next_page", "error"),
    [
        ("31-30&nbsp;/&nbsp;131", False, "started after it ended"),
        ("1-30&nbsp;/&nbsp;29", False, "exceeded the total records"),
        ("2-31&nbsp;/&nbsp;131", False, "did not start at record 1"),
        ("1-29&nbsp;/&nbsp;131", False, "record count did not match"),
        ("1-30&nbsp;/&nbsp;30", False, "final results page had a next-page URL"),
        ("1-30&nbsp;/&nbsp;131", True, "a non-final results page did not have a next-page URL"),
    ],
)
def test_rejects_inconsistent_pagination_ranges(
    replacement: str,
    replace_next_page: bool,
    error: str,
) -> None:
    html = _fixture("results-open-page-1.html")
    if replace_next_page:
        html = html.replace("currentPage=2", "currentPage=9")
    else:
        html = html.replace("1-30&nbsp;/&nbsp;131", replacement)

    with pytest.raises(ParserContractError, match=error):
        parse_search_results(html, _RESULTS_URL)


def test_rejects_conflicting_urls_for_one_logical_page() -> None:
    html = _fixture("results-open-page-1.html").replace(
        "recordNum=31&currentPage=2",
        "recordNum=999&currentPage=2",
        1,
    )

    with pytest.raises(ParserContractError, match="conflicting URLs for pagination page 2"):
        parse_search_results(html, _RESULTS_URL)


def test_accepts_duplicate_pagination_urls_with_distinct_session_ids() -> None:
    html = _fixture("results-open-page-1.html").replace(
        "sessionID=SESSION_ID&document_search_status=Active&selected_org_active=All&"
        "search_DocType=All&search_DocTypeQual=All&recordNum=31&currentPage=2",
        "sessionID=OTHER_SESSION&document_search_status=Active&selected_org_active=All&"
        "search_DocType=All&search_DocTypeQual=All&recordNum=31&currentPage=2",
        1,
    )

    page = parse_search_results(html, _RESULTS_URL)

    assert page.pagination is not None
    assert page.pagination.next_request_url is not None


def test_tracker_rejects_repeated_pages_and_source_ids() -> None:
    first_page = parse_search_results(_fixture("results-open-page-1.html"), _RESULTS_URL)
    second_page = parse_search_results(_fixture("results-open-page-2.html"), _RESULTS_URL)
    tracker = SearchPageTracker()

    tracker.add(first_page)
    tracker.add(second_page)

    with pytest.raises(ParserContractError, match="duplicate search-results page"):
        tracker.add(first_page)
