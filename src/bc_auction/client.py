import time
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from urllib.parse import urljoin, urlparse

import httpx

from bc_auction.encoding import DecodedPage, decode_html


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
        url = urljoin(self._base_url, path_or_url)
        self._check_host(url)
        self._wait_for_request_slot()

        response = self._client.get(url)
        response.raise_for_status()

        return FetchedPage(
            url=str(response.url),
            status_code=response.status_code,
            body=response.content,
            content_type=response.headers.get("content-type"),
            fetched_at=datetime.now(UTC),
        )

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
