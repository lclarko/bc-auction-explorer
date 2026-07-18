from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

import bc_auction.client as client_module
from bc_auction.client import AuctionClient, OpenAuctionSearch
from bc_auction.errors import ResponseContractError

_FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def test_client_keeps_raw_body_and_content_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"].startswith("bc-auction-explorer/")
        return httpx.Response(
            200,
            content="Café".encode("windows-1252"),
            headers={"content-type": "text/html; charset=windows-1252"},
            request=request,
        )

    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        page = client.get("/open.dll/welcome")

    assert page.decode().text == "Café"


def test_prepared_search_exposes_only_public_product_groups() -> None:
    assert tuple(OpenAuctionSearch.__dataclass_fields__) == ("product_groups",)


def test_client_records_aggregate_retry_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(429, headers={"retry-after": "1"}, request=request)
        return httpx.Response(200, content=b"results", request=request)

    durations = iter((17, 23))
    monkeypatch.setattr(client_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(client_module, "_elapsed_milliseconds", lambda _: next(durations))
    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        client.get("/results")
        metrics = client.metrics

    assert metrics.requests_attempted == 2
    assert metrics.responses_received == 2
    assert metrics.retries == 1
    assert metrics.rate_limit_responses == 1
    assert metrics.transport_errors == 0
    assert metrics.request_duration_ms == 40
    assert metrics.request_wait_duration_ms == 0
    assert metrics.retry_wait_duration_ms == 1000


def test_client_rejects_another_host() -> None:
    with AuctionClient(min_request_interval=0) as client:
        with pytest.raises(ValueError):
            client.get("https://example.com/")


def test_client_allows_same_host_redirect() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/results"}, request=request)
        return httpx.Response(200, content=b"results", request=request)

    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        page = client.get("/start")

    assert page.url == "https://www.bcauction.ca/results"
    assert requested_paths == ["/start", "/results"]


def test_client_rejects_cross_host_redirect_before_requesting_target() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(
                302,
                headers={"location": "https://example.com/results"},
                request=request,
            )
        return httpx.Response(200, request=request)

    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="outside the configured host"):
            client.get("/start")

    assert requested_urls == ["https://www.bcauction.ca/start"]


def test_client_rejects_same_host_http_redirect_before_requesting_target() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "http://www.bcauction.ca/results"},
            request=request,
        )

    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="outside the configured host"):
            client.get("/start")

    assert requested_urls == ["https://www.bcauction.ca/start"]


def test_client_rejects_direct_same_host_http_url() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, content=b"<html>unexpected</html>", request=request)

    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="outside the configured host"):
            client.get("http://www.bcauction.ca/results")

    assert requested_urls == []


def test_client_rejects_redirect_without_a_location() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, request=request)

    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="did not contain a Location"):
            client.get("/start")


def test_client_rejects_redirect_loop_before_repeating_request() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        location = "/next" if request.url.path == "/start" else "/start"
        return httpx.Response(302, headers={"location": location}, request=request)

    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="redirect loop detected"):
            client.get("/start")

    assert requested_paths == ["/start", "/next"]


def test_client_rejects_redirects_beyond_limit() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/first"}, request=request)
        return httpx.Response(302, headers={"location": "/second"}, request=request)

    with AuctionClient(
        min_request_interval=0,
        max_redirects=1,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(ValueError, match="redirect limit exceeded"):
            client.get("/start")

    assert requested_paths == ["/start", "/first"]


@pytest.mark.parametrize(
    ("status_code", "expected_method"),
    [
        (301, "GET"),
        (302, "GET"),
        (303, "GET"),
        (307, "POST"),
        (308, "POST"),
    ],
)
def test_client_preserves_post_redirect_method_semantics(
    status_code: int,
    expected_method: str,
) -> None:
    redirected_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal redirected_request
        if request.url.path == "/start":
            assert request.method == "POST"
            assert request.content == b"Keyword=truck"
            return httpx.Response(
                status_code,
                headers={"location": "/results"},
                request=request,
            )
        redirected_request = request
        return httpx.Response(200, content=b"<html>results</html>", request=request)

    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        client.post_form("/start", (("Keyword", "truck"),))

    assert redirected_request is not None
    assert redirected_request.method == expected_method
    if expected_method == "GET":
        assert redirected_request.content == b""
        assert "content-type" not in redirected_request.headers
    else:
        assert redirected_request.content == b"Keyword=truck"
        assert redirected_request.headers["content-type"] == "application/x-www-form-urlencoded"


def test_client_submits_open_auction_search() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/open.dll/welcome":
            return httpx.Response(200, content=_fixture("welcome.html"), request=request)
        if request.url.path == "/open.dll/showWelcomeContent":
            assert request.headers["cookie"] == "sessionID=|SESSION_ID|"
            return httpx.Response(200, content=_fixture("welcome-content.html"), request=request)
        if request.url.path == "/open.dll/submitLogin":
            return httpx.Response(
                302,
                headers={"location": "/open.dll/showDocumentSearch?sessionID=SESSION_ID"},
                request=request,
            )
        if request.url.path == "/open.dll/showDocumentSearch":
            return httpx.Response(200, content=_fixture("search-entry.html"), request=request)
        if request.url.path == "/open.dll/submitDocSearch":
            assert request.method == "POST"
            assert request.headers["cookie"] == "sessionID=|SESSION_ID|"
            fields = parse_qs(request.content.decode(), keep_blank_values=True)
            assert fields["Keyword"] == ["truck"]
            assert fields["display_order"] == ["HighestPrice"]
            assert fields["productDisID"] == ["simpleAll"]
            assert fields["dllAnchor"] == ["allOpenOpportunities"]
            assert fields["productDesc"] == ["Browse All Open Auctions"]
            assert fields["field_disID1"] == ["5810716"]
            assert fields["UseProfile"] == [""]
            assert fields["sessionID"] == ["SESSION_ID"]
            return httpx.Response(200, content=b"<html>results</html>", request=request)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        page = client.search_open_auctions(keyword="truck", display_order="HighestPrice")

    assert page.body == b"<html>results</html>"


def test_client_rejects_cross_host_post_redirect() -> None:
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        if request.url.host == "www.bcauction.ca":
            return httpx.Response(
                302,
                headers={"location": "https://example.com/results"},
                request=request,
            )
        return httpx.Response(200, request=request)

    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="outside the configured host"):
            client.post_form("/open.dll/submitDocSearch", (("Keyword", "truck"),))

    assert requested_hosts == ["www.bcauction.ca"]


def test_client_follows_item_detail_frames() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/open.dll/showDisplayDocument":
            return httpx.Response(200, content=_fixture("item-detail-frame.html"), request=request)
        if request.url.path == "/open.dll/showWorking":
            return httpx.Response(
                200,
                content=_fixture("item-detail-working.html"),
                request=request,
            )
        if request.url.path == "/open.dll/showDocSummary":
            return httpx.Response(200, content=_fixture("item-detail.html"), request=request)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        page = client.get_item_detail(
            "/open.dll/showDisplayDocument?sessionID=SESSION_ID&disID=8733643"
        )

    assert page.url == (
        "https://www.bcauction.ca/open.dll/showDocSummary?sessionID=SESSION_ID&disID=8733643"
    )


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"base_url": "/relative"}, "absolute HTTP URL"),
        ({"min_request_interval": -1}, "min_request_interval"),
        ({"timeout": 0}, "timeout"),
        ({"max_redirects": -1}, "max_redirects"),
        ({"max_retries": -1}, "max_retries"),
        ({"retry_backoff": -1}, "retry_backoff"),
        ({"max_html_bytes": 0}, "max_html_bytes"),
    ],
)
def test_client_rejects_invalid_configuration(kwargs: dict[str, object], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        AuctionClient(**kwargs)


def test_client_retries_a_connection_failure() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("connection failed", request=request)
        return httpx.Response(200, content=b"<html>recovered</html>", request=request)

    with AuctionClient(
        min_request_interval=0,
        max_retries=1,
        retry_backoff=0,
        transport=httpx.MockTransport(handler),
    ) as client:
        page = client.get("/retries")

    assert page.body == b"<html>recovered</html>"
    assert attempts == 2


@pytest.mark.parametrize("status_code", [429, 502, 503, 504])
def test_client_retries_the_supported_response_statuses(status_code: int) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(status_code, request=request)
        return httpx.Response(200, content=b"<html>recovered</html>", request=request)

    with AuctionClient(
        min_request_interval=0,
        max_retries=1,
        retry_backoff=0,
        transport=httpx.MockTransport(handler),
    ) as client:
        client.get("/retries")

    assert attempts == 2


def test_client_honors_retry_after_with_a_bounded_delay(monkeypatch) -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, headers={"retry-after": "2"}, request=request)
        return httpx.Response(200, content=b"<html>recovered</html>", request=request)

    monkeypatch.setattr(client_module.time, "sleep", delays.append)
    with AuctionClient(
        min_request_interval=0,
        max_retries=1,
        retry_backoff=0,
        transport=httpx.MockTransport(handler),
    ) as client:
        client.get("/retries")

    assert delays == [2.0]


def test_client_honors_the_full_retry_after_delay(monkeypatch) -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, headers={"retry-after": "30"}, request=request)
        return httpx.Response(200, content=b"<html>recovered</html>", request=request)

    monkeypatch.setattr(client_module.time, "sleep", delays.append)
    with AuctionClient(
        min_request_interval=0,
        max_retries=1,
        retry_backoff=0,
        transport=httpx.MockTransport(handler),
    ) as client:
        client.get("/retries")

    assert delays == [30.0]


def test_client_falls_back_when_retry_after_is_not_finite(monkeypatch) -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, headers={"retry-after": "inf"}, request=request)
        return httpx.Response(200, content=b"<html>recovered</html>", request=request)

    monkeypatch.setattr(client_module.time, "sleep", delays.append)
    with AuctionClient(
        min_request_interval=0,
        max_retries=1,
        retry_backoff=0.5,
        transport=httpx.MockTransport(handler),
    ) as client:
        client.get("/retries")

    assert delays == [0.5]


def test_client_does_not_retry_an_ordinary_server_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500, request=request)

    with AuctionClient(
        min_request_interval=0,
        max_retries=2,
        retry_backoff=0,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            client.get("/no-retry")

    assert attempts == 1


@pytest.mark.parametrize(
    ("body", "headers", "max_html_bytes", "error"),
    [
        (b"", {}, 100, "empty"),
        (b"<html>too large</html>", {}, 4, "maximum size"),
        (b"\x00\x01\x02", {}, 100, "binary"),
        (b"{\"unexpected\": true}", {"content-type": "application/json"}, 100, "content type"),
    ],
)
def test_client_rejects_invalid_html_responses(
    body: bytes,
    headers: dict[str, str],
    max_html_bytes: int,
    error: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers=headers, request=request)

    with AuctionClient(
        min_request_interval=0,
        max_html_bytes=max_html_bytes,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(ResponseContractError, match=error):
            client.get("/invalid")


def test_client_accepts_textual_legacy_content_types() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html>legacy response</html>",
            headers={"content-type": "application/octet-stream"},
            request=request,
        )

    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        page = client.get("/legacy")

    assert page.body == b"<html>legacy response</html>"
