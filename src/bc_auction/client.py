import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from bc_auction.encoding import DecodedPage, decode_html
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
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._base_host = urlparse(base_url).netloc.casefold()
        self._min_request_interval = min_request_interval
        self._last_request_started: float | None = None
        self._client = httpx.Client(
            follow_redirects=True,
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

    def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        data: Sequence[tuple[str, str]] | None = None,
    ) -> FetchedPage:
        url = urljoin(self._base_url, path_or_url)
        self._check_host(url)
        self._wait_for_request_slot()

        if data is None:
            response = self._client.request(method, url)
        else:
            response = self._client.request(
                method,
                url,
                content=urlencode(data),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        for redirect in response.history:
            self._check_host(str(redirect.url))
        self._check_host(str(response.url))
        response.raise_for_status()

        return FetchedPage(
            url=str(response.url),
            status_code=response.status_code,
            body=response.content,
            content_type=response.headers.get("content-type"),
            fetched_at=datetime.now(UTC),
        )

    def _set_session_cookie(self, session_id: str, source_url: str) -> None:
        hostname = urlparse(source_url).hostname
        if hostname is None:
            raise ValueError("unable to set a session cookie without a hostname")
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
