import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag
from pydantic import HttpUrl, TypeAdapter

from bc_auction.errors import ParserContractError
from bc_auction.models import (
    AuctionStatus,
    SearchPagination,
    SearchResultRecord,
    SearchResultsPage,
)

_EMPTY_RESULT_TEXT = "There were no results for the specified search."
_PAGE_RANGE = re.compile(r"(\d+)\s*-\s*(\d+)\s*/\s*(\d+)")
_OPEN_WINDOW_URL = re.compile(r"openWindow\(\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_AUCTION_NUMBER = re.compile(r"^[A-Z]\d+$")
_OPEN_HEADINGS = frozenset({"Auction No", "Published Date", "Closing Date", "High Bid", "Location"})
_RESULTS_PAGE_TITLES = frozenset({"Browse Auctions", "Advanced Auction Search"})
_PACIFIC_TIME = ZoneInfo("America/Vancouver")
_HTTP_URL = TypeAdapter(HttpUrl)


@dataclass(frozen=True, slots=True)
class _ResultColumnMap:
    summary_cell_count: int
    detail_cell_count: int
    auction_number: int
    title: int
    current_bid: int
    closing_at: int
    title_in_detail: bool
    closing_at_in_detail: bool
    location: int | None = None


_OPEN_COLUMNS = _ResultColumnMap(
    summary_cell_count=5,
    detail_cell_count=7,
    auction_number=1,
    title=2,
    current_bid=3,
    closing_at=4,
    title_in_detail=False,
    closing_at_in_detail=True,
    location=4,
)


@dataclass(slots=True)
class SearchPageTracker:
    _page_fingerprints: set[tuple[str, ...]] = field(default_factory=set)
    _source_ids: set[str] = field(default_factory=set)

    def add(self, page: SearchResultsPage) -> None:
        source_ids = tuple(record.source_id for record in page.records)
        if not source_ids:
            return
        if source_ids in self._page_fingerprints:
            raise ParserContractError("duplicate search-results page")

        duplicates = self._source_ids.intersection(source_ids)
        if duplicates:
            duplicate_ids = ", ".join(sorted(duplicates))
            raise ParserContractError(f"duplicate source IDs across pages: {duplicate_ids}")

        self._page_fingerprints.add(source_ids)
        self._source_ids.update(source_ids)


def parse_search_results(html: str, page_url: str) -> SearchResultsPage:
    soup = BeautifulSoup(html, "lxml")
    _validate_page_identity(soup)

    if _EMPTY_RESULT_TEXT in _text(soup):
        return SearchResultsPage()

    columns = _detect_columns(soup)
    item_links = _item_links(soup, columns)
    if not item_links:
        raise ParserContractError(
            "results page did not contain auction rows or an empty-results marker"
        )

    records = tuple(_parse_record(link, columns, page_url) for link in item_links)
    _ensure_unique_source_ids(records)
    pagination = _parse_pagination(soup, page_url)
    _validate_pagination(pagination, record_count=len(records))

    return SearchResultsPage(records=records, pagination=pagination)


def _validate_page_identity(soup: BeautifulSoup) -> None:
    title = _text(soup.title) if soup.title is not None else ""
    page_titles = {_text(element) for element in soup.select(".pageTitle")}
    if title not in _RESULTS_PAGE_TITLES and "Advanced Auction Search" not in page_titles:
        raise ParserContractError("response was not a BC Auction results page")
    if soup.find("form", action="submitDocSearch") is None:
        raise ParserContractError("results page did not contain the search form")


def _detect_columns(soup: BeautifulSoup) -> _ResultColumnMap:
    headings = {_text(cell) for cell in soup.select("td.searchResultsHeader")}
    if _OPEN_HEADINGS <= headings:
        return _OPEN_COLUMNS

    expected = ", ".join(sorted(_OPEN_HEADINGS))
    raise ParserContractError(f"results page was missing a recognized heading set: {expected}")


def _parse_record(link: Tag, columns: _ResultColumnMap, base_url: str) -> SearchResultRecord:
    summary_row = _summary_row(link, columns)
    summary_cells = _content_cells(summary_row)
    if len(summary_cells) != columns.summary_cell_count:
        raise ParserContractError("auction summary row did not have the expected content cells")

    source_id = _text(summary_cells[columns.auction_number])
    if not _AUCTION_NUMBER.fullmatch(source_id):
        raise ParserContractError("auction summary row did not contain a valid auction number")

    detail_row = summary_row.find_next_sibling("tr")
    if not isinstance(detail_row, Tag):
        raise ParserContractError("auction summary row did not have a detail row")
    detail_cells = _content_cells(detail_row)
    if len(detail_cells) != columns.detail_cell_count:
        raise ParserContractError("auction detail row did not have the expected content cells")

    title_cell = (
        detail_cells[columns.title] if columns.title_in_detail else summary_cells[columns.title]
    )
    title_marker = title_cell.select_one("span.searchResultsTitle")
    title = _text(title_marker) if title_marker is not None else _text(title_cell)
    if not title:
        raise ParserContractError("auction result did not contain a title")

    closing_cell = (
        detail_cells[columns.closing_at]
        if columns.closing_at_in_detail
        else summary_cells[columns.closing_at]
    )
    status_raw, status = _parse_status(summary_cells[columns.auction_number])
    location_raw = _text(summary_cells[columns.location]) if columns.location is not None else None
    return SearchResultRecord(
        source_url=_item_url(link, base_url),
        source_id=source_id,
        title=title,
        location_raw=location_raw,
        current_bid=_parse_decimal(_text(summary_cells[columns.current_bid]), "current bid"),
        minimum_bid=None,
        bid_count=None,
        closing_at=_parse_closing_at(_text(closing_cell)),
        status_raw=status_raw,
        status=status,
        summary_cells=tuple(_text(cell) for cell in summary_cells),
        detail_text=_text(detail_row),
    )


def _item_links(soup: BeautifulSoup, columns: _ResultColumnMap) -> list[Tag]:
    groups: dict[int, list[Tag]] = {}
    for link in soup.select("a.searchResultsBodyLink"):
        summary_row = _summary_row(link, columns)
        parent = summary_row.parent
        if not isinstance(parent, Tag) or parent.name != "table":
            raise ParserContractError("auction summary row did not belong to a table")
        groups.setdefault(id(parent), []).append(link)

    complete_groups = [
        links
        for links in groups.values()
        if all(_summary_row(link, columns).find_next_sibling("tr") is not None for link in links)
    ]
    if not complete_groups:
        raise ParserContractError("results page did not contain a complete auction row group")
    return max(complete_groups, key=len)


def _summary_row(link: Tag, columns: _ResultColumnMap) -> Tag:
    for row in link.find_parents("tr"):
        if len(_content_cells(row)) == columns.summary_cell_count:
            return row
    raise ParserContractError("auction link did not have a summary row")


def _content_cells(row: Tag) -> tuple[Tag, ...]:
    return tuple(
        cell
        for cell in row.find_all("td", recursive=False)
        if "resultsLines" not in str(cell.get("class", ""))
    )


def _item_url(link: Tag, base_url: str) -> HttpUrl:
    href = str(link.get("href", ""))
    match = _OPEN_WINDOW_URL.search(href)
    if match is None:
        raise ParserContractError("auction link did not contain a detail URL")

    item_url = urljoin(base_url, match.group(1))
    parsed_item_url = urlparse(item_url)
    base_host = urlparse(base_url).netloc.casefold()
    if parsed_item_url.netloc.casefold() != base_host:
        raise ParserContractError("auction detail URL left the configured host")
    if not parsed_item_url.path.casefold().endswith("/showdisplaydocument"):
        raise ParserContractError("auction detail URL did not use showDisplayDocument")
    return _HTTP_URL.validate_python(item_url)


def _parse_status(auction_cell: Tag) -> tuple[str | None, AuctionStatus]:
    image_sources = [str(image.get("src", "")) for image in auction_cell.find_all("img")]
    for image_source in image_sources:
        lowered = image_source.casefold()
        if "closed_withdrawn" in lowered:
            return image_source.rsplit("/", maxsplit=1)[-1], AuctionStatus.WITHDRAWN
        if "closeddoc" in lowered:
            return image_source.rsplit("/", maxsplit=1)[-1], AuctionStatus.CLOSED
        if "opendocument" in lowered:
            return image_source.rsplit("/", maxsplit=1)[-1], AuctionStatus.OPEN
    return None, AuctionStatus.UNKNOWN


def _parse_decimal(value: str, field_name: str) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value.replace(",", "").replace("$", ""))
    except InvalidOperation as exc:
        raise ParserContractError(f"auction {field_name} was not a decimal") from exc


def _parse_closing_at(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y/%m/%d %H:%M").replace(tzinfo=_PACIFIC_TIME)
    except ValueError as exc:
        raise ParserContractError("auction closing date was not in the expected format") from exc


def _parse_pagination(soup: BeautifulSoup, base_url: str) -> SearchPagination:
    range_match = _PAGE_RANGE.search(_text(soup))
    if range_match is None:
        raise ParserContractError("results page did not contain a record range")
    record_start, record_end, total_records = (int(value) for value in range_match.groups())

    current_pages = {
        int(text)
        for span in soup.select("td.alignCenter span.boldText")
        if (text := _text(span)).isdigit()
    }
    if len(current_pages) != 1:
        raise ParserContractError("results page did not identify one current page")
    current_page = current_pages.pop()

    page_urls = _page_urls(soup, base_url)
    return SearchPagination(
        current_page=current_page,
        record_start=record_start,
        record_end=record_end,
        total_records=total_records,
        page_urls=tuple(url for _, url in sorted(page_urls.items())),
        next_page_url=page_urls.get(current_page + 1),
    )


def _validate_pagination(pagination: SearchPagination, record_count: int) -> None:
    if pagination.record_start > pagination.record_end:
        raise ParserContractError("results page record range started after it ended")
    if pagination.record_end > pagination.total_records:
        raise ParserContractError("results page record range exceeded the total records")
    if pagination.current_page == 1 and pagination.record_start != 1:
        raise ParserContractError("the first results page did not start at record 1")

    expected_record_count = pagination.record_end - pagination.record_start + 1
    if record_count != expected_record_count:
        raise ParserContractError("results page record count did not match its record range")

    if pagination.record_end == pagination.total_records:
        if pagination.next_page_url is not None:
            raise ParserContractError("the final results page had a next-page URL")
        return
    if pagination.next_page_url is None:
        raise ParserContractError("a non-final results page did not have a next-page URL")

    next_page_number = _page_number(str(pagination.next_page_url))
    if next_page_number is None:
        raise ParserContractError("results page next-page URL did not contain a page number")
    if next_page_number <= pagination.current_page:
        raise ParserContractError("the next results page did not advance")


def _page_urls(soup: BeautifulSoup, base_url: str) -> dict[int, HttpUrl]:
    page_urls: dict[int, HttpUrl] = {}
    for link in soup.select('a[href*="submitDocSearch"]'):
        page_url = urljoin(base_url, str(link["href"]))
        current_page = _page_number(page_url, required=False)
        if current_page is None:
            continue
        parsed_url = _HTTP_URL.validate_python(page_url)
        existing_url = page_urls.get(current_page)
        if existing_url is not None and str(existing_url) != str(parsed_url):
            raise ParserContractError(
                f"results page had conflicting URLs for pagination page {current_page}"
            )
        page_urls[current_page] = parsed_url
    return page_urls


def _page_number(page_url: str, *, required: bool = True) -> int | None:
    current_page = parse_qs(urlparse(page_url).query).get("currentPage")
    if current_page is not None and len(current_page) == 1 and current_page[0].isdigit():
        return int(current_page[0])
    if required:
        raise ParserContractError("results page next-page URL did not contain a page number")
    return None


def _ensure_unique_source_ids(records: tuple[SearchResultRecord, ...]) -> None:
    source_ids = [record.source_id for record in records]
    if len(source_ids) == len(set(source_ids)):
        return
    raise ParserContractError("results page contained duplicate source IDs")


def _text(node: Tag | BeautifulSoup | None) -> str:
    if node is None:
        return ""
    return str(" ".join(node.get_text(" ", strip=True).split()))
