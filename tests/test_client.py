from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from bc_auction.client import AuctionClient

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


def test_client_rejects_another_host() -> None:
    with AuctionClient(min_request_interval=0) as client:
        with pytest.raises(ValueError):
            client.get("https://example.com/")


def test_client_allows_same_host_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/results"}, request=request)
        return httpx.Response(200, content=b"results", request=request)

    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        page = client.get("/start")

    assert page.url == "https://www.bcauction.ca/results"


def test_client_rejects_cross_host_final_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
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


def test_client_rejects_cross_host_redirect_history() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.bcauction.ca" and request.url.path == "/start":
            return httpx.Response(
                302,
                headers={"location": "https://example.com/continue"},
                request=request,
            )
        if request.url.host == "example.com":
            return httpx.Response(
                302,
                headers={"location": "https://www.bcauction.ca/results"},
                request=request,
            )
        return httpx.Response(200, request=request)

    with AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="outside the configured host"):
            client.get("/start")


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
    def handler(request: httpx.Request) -> httpx.Response:
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
