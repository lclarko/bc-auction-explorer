import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from bc_auction.encoding import DecodedPage, decode_html
from bc_auction.errors import ResponseContractError
from bc_auction.parsers.details import parse_detail_summary_url, parse_detail_working_url
from bc_auction.parsers.search import (
    parse_browse_url,
    parse_search_form,
    parse_session_id,
    parse_welcome_content_url,
)

_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
_RETRYABLE_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.ReadTimeout,
)
_HTML_CONTENT_TYPES = frozenset({"application/xhtml+xml", "text/html"})
_LEGACY_HTML_CONTENT_TYPES = frozenset({"application/octet-stream", "text/htm", "text/plain"})


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    status_code: int
    body: bytes
    content_type: str | None
    fetched_at: datetime

    def decode(self) -> DecodedPage:
        return decode_html(self.body, self.content_type)


class AuctionClient:
    def __init__(
        self,
        base_url: str = "https://www.bcauction.ca/",
        min_request_interval: float = 1.5,
        timeout: float = 20.0,
        max_redirects: int = 10,
        max_retries: int = 2,
        retry_backoff: float = 0.5,
        max_html_bytes: int = 5_000_000,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parsed_base_url = urlparse(base_url)
        if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
            raise ValueError("base_url must be an absolute HTTP URL")
        if min_request_interval < 0:
            raise ValueError("min_request_interval must be non-negative")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_redirects < 0:
            raise ValueError("max_redirects must be non-negative")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if retry_backoff < 0:
            raise ValueError("retry_backoff must be non-negative")
        if max_html_bytes < 1:
            raise ValueError("max_html_bytes must be positive")

        self._base_url = base_url
        self._base_host = parsed_base_url.netloc.casefold()
        self._min_request_interval = min_request_interval
        self._last_request_started: float | None = None
        self._max_redirects = max_redirects
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._max_html_bytes = max_html_bytes
        self._client = httpx.Client(
            follow_redirects=False,
            timeout=timeout,
            transport=transport,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": (
                    "bc-auction-explorer/0.1 "
                    "(+https://github.com/lclarko/bc-auction-explorer)"
                ),
            },
        )

    def __enter__(self) -> "AuctionClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(self, path_or_url: str) -> FetchedPage:
        return self._request("GET", path_or_url)

    def post_form(self, path_or_url: str, fields: Sequence[tuple[str, str]]) -> FetchedPage:
        return self._request("POST", path_or_url, data=fields)

    def search_open_auctions(
        self,
        *,
        keyword: str = "",
        display_order: str = "EndingFirst",
    ) -> FetchedPage:
        welcome_page = self.get("/open.dll/welcome?language=En")
        welcome_html = welcome_page.decode().text
        self._set_session_cookie(parse_session_id(welcome_html), welcome_page.url)

        welcome_content_url = parse_welcome_content_url(welcome_html, welcome_page.url)
        welcome_content_page = self.get(welcome_content_url)
        browse_url = parse_browse_url(welcome_content_page.decode().text, welcome_content_page.url)
        browse_page = self.get(browse_url)
        search_form = parse_search_form(browse_page.decode().text, browse_page.url)
        self._set_session_cookie(search_form.session_id, browse_page.url)

        return self.post_form(
            search_form.action_url,
            search_form.open_auction_fields(keyword=keyword, display_order=display_order),
        )

    def get_item_detail(self, path_or_url: str) -> FetchedPage:
        detail_frame_page = self.get(path_or_url)
        working_url = parse_detail_working_url(
            detail_frame_page.decode().text,
            detail_frame_page.url,
        )
        working_page = self.get(working_url)
        summary_url = parse_detail_summary_url(working_page.decode().text, working_page.url)
        return self.get(summary_url)

    def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        data: Sequence[tuple[str, str]] | None = None,
    ) -> FetchedPage:
        url = urljoin(self._base_url, path_or_url)
        self._check_host(url)
        request_method = method
        request_data = data
        redirects_followed = 0
        visited_requests = {(request_method, url)}

        while True:
            response = self._send_with_retries(request_method, url, request_data)
            self._check_host(str(response.url))

            if not response.is_redirect:
                response.raise_for_status()
                self._validate_html_response(response)
                return FetchedPage(
                    url=str(response.url),
                    status_code=response.status_code,
                    body=response.content,
                    content_type=response.headers.get("content-type"),
                    fetched_at=datetime.now(UTC),
                )

            if redirects_followed >= self._max_redirects:
                raise ValueError("redirect limit exceeded")

            location = response.headers.get("location")
            if location is None:
                raise ValueError("redirect response did not contain a Location header")
            redirect_url = urljoin(str(response.url), location)
            self._check_host(redirect_url)

            redirect_method = self._redirect_method(request_method, response.status_code)
            redirect_data = request_data if redirect_method == request_method else None
            request_key = (redirect_method, redirect_url)
            if request_key in visited_requests:
                raise ValueError("redirect loop detected")

            redirects_followed += 1
            visited_requests.add(request_key)
            request_method = redirect_method
            request_data = redirect_data
            url = redirect_url

    def _send_with_retries(
        self,
        method: str,
        url: str,
        data: Sequence[tuple[str, str]] | None,
    ) -> httpx.Response:
        retries_used = 0
        while True:
            self._wait_for_request_slot()
            try:
                response = self._send_request(method, url, data)
            except _RETRYABLE_TRANSPORT_ERRORS:
                if retries_used >= self._max_retries:
                    raise
                self._sleep_for_retry(retries_used)
                retries_used += 1
                continue

            should_retry = (
                response.status_code in _RETRYABLE_STATUS_CODES
                and retries_used < self._max_retries
            )
            if not should_retry:
                return response

            retry_after = self._retry_after_seconds(response)
            response.close()
            self._sleep_for_retry(retries_used, retry_after=retry_after)
            retries_used += 1

    def _send_request(
        self,
        method: str,
        url: str,
        data: Sequence[tuple[str, str]] | None,
    ) -> httpx.Response:
        if data is None:
            return self._client.request(method, url)
        return self._client.request(
            method,
            url,
            content=urlencode(data),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    @staticmethod
    def _redirect_method(method: str, status_code: int) -> str:
        if status_code in {httpx.codes.SEE_OTHER, httpx.codes.FOUND} and method != "HEAD":
            return "GET"
        if status_code == httpx.codes.MOVED_PERMANENTLY and method == "POST":
            return "GET"
        return method

    def _set_session_cookie(self, session_id: str, source_url: str) -> None:
        hostname = urlparse(source_url).hostname
        if hostname is None:
            raise ValueError("unable to set a session cookie without a hostname")
        # BC Auction's welcome JavaScript appends the session ID between pipe delimiters.
        self._client.cookies.set("sessionID", f"|{session_id}|", domain=hostname, path="/")

    def _check_host(self, url: str) -> None:
        if urlparse(url).netloc.casefold() != self._base_host:
            raise ValueError("refusing to request a URL outside the configured host")

    def _validate_html_response(self, response: httpx.Response) -> None:
        content_length = response.headers.get("content-length")
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > self._max_html_bytes
        ):
            raise ResponseContractError("HTML response exceeded the configured maximum size")

        body = response.content
        if not body:
            raise ResponseContractError("HTML response body was empty")
        if len(body) > self._max_html_bytes:
            raise ResponseContractError("HTML response exceeded the configured maximum size")
        if self._contains_binary_data(body):
            raise ResponseContractError("HTML response contained clearly binary data")

        content_type = response.headers.get("content-type")
        if content_type is None:
            return
        media_type = content_type.split(";", maxsplit=1)[0].strip().casefold()
        if media_type in _HTML_CONTENT_TYPES or media_type in _LEGACY_HTML_CONTENT_TYPES:
            return
        raise ResponseContractError("response content type was not accepted as HTML")

    def _sleep_for_retry(self, retries_used: int, *, retry_after: float | None = None) -> None:
        bounded_backoff = min(5.0, self._retry_backoff * (2**retries_used))
        delay = bounded_backoff if retry_after is None else min(5.0, retry_after)
        time.sleep(delay)

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        retry_after = response.headers.get("retry-after")
        if retry_after is None:
            return None
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                retry_after_at = parsedate_to_datetime(retry_after)
            except (TypeError, ValueError):
                return None
            if retry_after_at.tzinfo is None:
                retry_after_at = retry_after_at.replace(tzinfo=UTC)
            return max(0.0, (retry_after_at - datetime.now(UTC)).total_seconds())

    @staticmethod
    def _contains_binary_data(body: bytes) -> bool:
        if b"\x00" in body:
            return True
        sample = body[:4096]
        control_bytes = sum(byte < 9 or 14 <= byte < 32 for byte in sample)
        return control_bytes * 20 > len(sample)

    def _wait_for_request_slot(self) -> None:
        now = time.monotonic()
        if self._last_request_started is not None:
            elapsed = now - self._last_request_started
            remaining = self._min_request_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_started = time.monotonic()
