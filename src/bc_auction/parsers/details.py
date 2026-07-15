import hashlib
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from pydantic import HttpUrl, TypeAdapter

from bc_auction.errors import ParserContractError
from bc_auction.models import AuctionDetailRecord, AuctionStatus, SearchResultRecord

_PACIFIC_TIME = ZoneInfo("America/Vancouver")
_HTTP_URL = TypeAdapter(HttpUrl)
_WINDOW_LOCATION = re.compile(
    r"window\.location\s*=\s*[\"'](?P<url>[^\"']+)[\"']",
    re.IGNORECASE,
)


def parse_item_detail(html: str, page_url: str) -> AuctionDetailRecord:
    soup = BeautifulSoup(html, "lxml")
    _validate_page_identity(soup)

    source_id = _label_value(soup, "Auction Number:")
    if not source_id:
        raise ParserContractError("auction detail did not contain an auction number")

    closing_at = _parse_closing_at(
        _label_value(soup, "Close Date & Time:"),
        _label_value(soup, "Time Zone:"),
    )
    status_raw, status = _parse_status(soup)
    return AuctionDetailRecord(
        source_url=_HTTP_URL.validate_python(page_url),
        source_id=source_id,
        title=_required_text(soup.select_one("td.doc_userDocTitle"), "title"),
        description=_section_text(soup, "Auction Details:"),
        category_raw=_text(soup.select_one("td.doc_subUserDocTitle")) or None,
        location_raw=_label_value(soup, "Location:") or None,
        pickup_details=_section_text(soup, "Shipping Details:"),
        current_bid=_parse_decimal(
            _current_bid_value(soup),
            "current high bid",
        ),
        minimum_bid=_parse_decimal(_input_value(soup, "MinimumBid"), "minimum bid"),
        bid_count=_parse_int(_label_value(soup, "Number Of Bids:"), "bid count"),
        closing_at=closing_at,
        status_raw=status_raw,
        status=status,
        image_urls=_image_urls(soup, page_url),
        content_hash=_content_hash(soup),
    )


def parse_detail_working_url(html: str, page_url: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    working_urls = [
        _detail_route_url(str(frame["src"]), page_url, "showWorking")
        for frame in soup.select("frame[src]")
        if urlparse(urljoin(page_url, str(frame["src"]))).path.casefold().endswith("/showworking")
    ]
    if len(working_urls) != 1:
        raise ParserContractError("item detail frame did not contain one working-page URL")
    return working_urls[0]


def parse_detail_summary_url(html: str, page_url: str) -> str:
    summary_urls = [
        _detail_route_url(match.group("url"), page_url, "showDocSummary")
        for match in _WINDOW_LOCATION.finditer(html)
        if (
            urlparse(urljoin(page_url, match.group("url"))).path.casefold().endswith(
                "/showdocsummary"
            )
        )
    ]
    if len(summary_urls) != 1:
        raise ParserContractError("item detail working page did not contain one summary URL")
    return summary_urls[0]


def reconcile_search_result(
    search_result: SearchResultRecord,
    detail: AuctionDetailRecord,
) -> AuctionDetailRecord:
    if search_result.source_id != detail.source_id:
        raise ParserContractError("search result and detail page had different auction numbers")
    if _normalize_text(search_result.title) != _normalize_text(detail.title):
        raise ParserContractError("search result and detail page had different titles")

    return detail.model_copy(
        update={
            "source_url": search_result.source_url,
            "location_raw": detail.location_raw or search_result.location_raw,
            "current_bid": (
                detail.current_bid if detail.current_bid is not None else search_result.current_bid
            ),
            "closing_at": (
                detail.closing_at if detail.closing_at is not None else search_result.closing_at
            ),
            "status_raw": detail.status_raw or search_result.status_raw,
            "status": (
                detail.status
                if detail.status is not AuctionStatus.UNKNOWN
                else search_result.status
            ),
        }
    )


def _validate_page_identity(soup: BeautifulSoup) -> None:
    title = _text(soup.title)
    if title and title != "Document Summary":
        raise ParserContractError("response was not a BC Auction item detail page")
    if not _text(soup.select_one("td.doc_userDocTitle")):
        raise ParserContractError("auction detail did not contain a document title")
    if not _input_value(soup, "AuctionNo"):
        raise ParserContractError("auction detail did not contain an auction number input")
    if _label_cell(soup, "Auction Number:") is None:
        raise ParserContractError("auction detail did not contain an auction number")


def _detail_route_url(source_url: str, page_url: str, endpoint: str) -> str:
    route_url = urljoin(page_url, source_url)
    parsed_route = urlparse(route_url)
    if parsed_route.netloc.casefold() != urlparse(page_url).netloc.casefold():
        raise ParserContractError("item detail route left the configured host")
    if not parsed_route.path.casefold().endswith(f"/{endpoint.casefold()}"):
        raise ParserContractError(f"item detail route did not use {endpoint}")
    return route_url


def _label_value(soup: BeautifulSoup, label: str) -> str:
    value_cell = _label_cell(soup, label)
    return _text(value_cell)


def _label_cell(soup: BeautifulSoup, label: str) -> Tag | None:
    for label_cell in soup.select("td.doc_labelColour, td.doc_tableHeader"):
        if _text(label_cell) != label:
            continue
        row = label_cell.find_parent("tr")
        if not isinstance(row, Tag):
            break
        direct_cells = row.find_all("td", recursive=False)
        for cell in reversed(direct_cells):
            if cell is label_cell:
                continue
            if _text(cell):
                return cell
    return None


def _current_bid_value(soup: BeautifulSoup) -> str:
    value_cell = _label_cell(soup, "Current High Bid:")
    if value_cell is None:
        return ""
    for child in value_cell.children:
        if not isinstance(child, NavigableString):
            continue
        value = _normalize_text(str(child))
        if value:
            return value
    return ""


def _section_text(soup: BeautifulSoup, label: str) -> str | None:
    for heading in soup.select("td.doc_tableHeader"):
        if _text(heading) != label:
            continue
        heading_row = heading.find_parent("tr")
        if not isinstance(heading_row, Tag):
            break
        content_row = heading_row.find_next_sibling("tr")
        if not isinstance(content_row, Tag):
            break
        content = _text(content_row.select_one("td.doc_fieldText"))
        return content or None
    return None


def _input_value(soup: BeautifulSoup, name: str) -> str:
    input_tag = soup.find("input", attrs={"name": name})
    if not isinstance(input_tag, Tag):
        return ""
    value = input_tag.get("value")
    return value if isinstance(value, str) else ""


def _parse_closing_at(value: str, timezone: str) -> datetime | None:
    if not value:
        return None
    if timezone != "PT":
        raise ParserContractError("auction detail had an unsupported timezone")
    try:
        return datetime.strptime(value, "%Y/%m/%d %H:%M").replace(tzinfo=_PACIFIC_TIME)
    except ValueError as exc:
        raise ParserContractError("auction detail had an invalid closing date") from exc


def _parse_status(soup: BeautifulSoup) -> tuple[str | None, AuctionStatus]:
    form = soup.find("form", action=True)
    if not isinstance(form, Tag):
        return None, AuctionStatus.UNKNOWN
    action = str(form["action"])
    is_bid = parse_qs(urlparse(action).query).get("isbid")
    if is_bid == ["Y"]:
        return "isbid=Y", AuctionStatus.OPEN
    return None, AuctionStatus.UNKNOWN


def _parse_decimal(value: str, field_name: str) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value.replace(",", "").replace("$", ""))
    except InvalidOperation as exc:
        raise ParserContractError(f"auction detail {field_name} was not a decimal") from exc


def _parse_int(value: str, field_name: str) -> int | None:
    if not value:
        return None
    if not value.isdigit():
        raise ParserContractError(f"auction detail {field_name} was not an integer")
    return int(value)


def _image_urls(soup: BeautifulSoup, page_url: str) -> tuple[HttpUrl, ...]:
    image_urls: list[HttpUrl] = []
    page_host = urlparse(page_url).netloc.casefold()
    for image in soup.select('img[src*="Pictures/"]'):
        image_url = urljoin(page_url, str(image["src"]))
        if urlparse(image_url).netloc.casefold() != page_host:
            raise ParserContractError("auction detail image URL left the configured host")
        image_urls.append(_HTTP_URL.validate_python(image_url))
    return tuple(image_urls)


def _content_hash(soup: BeautifulSoup) -> str:
    normalized = BeautifulSoup(str(soup), "lxml")
    for node in normalized.select("script, style"):
        node.decompose()
    return hashlib.sha256(_normalize_text(_text(normalized)).encode()).hexdigest()


def _required_text(node: Tag | None, field_name: str) -> str:
    value = _text(node)
    if not value:
        raise ParserContractError(f"auction detail did not contain a {field_name}")
    return value


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _text(node: Tag | BeautifulSoup | None) -> str:
    if node is None:
        return ""
    return str(" ".join(node.get_text(" ", strip=True).split()))
