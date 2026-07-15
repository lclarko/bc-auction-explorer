import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from bc_auction.encoding import DecodedPage, decode_html
from bc_auction.parsers.details import parse_detail_summary_url, parse_detail_working_url
from bc_auction.parsers.search import (
    parse_browse_url,
    parse_search_form,
    parse_session_id,
    parse_welcome_content_url,
)


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
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if max_redirects < 0:
            raise ValueError("max_redirects must be non-negative")

        self._base_url = base_url
        self._base_host = urlparse(base_url).netloc.casefold()
        self._min_request_interval = min_request_interval
        self._last_request_started: float | None = None
        self._max_redirects = max_redirects
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
            self._wait_for_request_slot()
            response = self._send_request(request_method, url, request_data)
            self._check_host(str(response.url))

            if not response.is_redirect:
                response.raise_for_status()
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

    def _wait_for_request_slot(self) -> None:
        now = time.monotonic()
        if self._last_request_started is not None:
            elapsed = now - self._last_request_started
            remaining = self._min_request_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_started = time.monotonic()
