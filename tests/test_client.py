import httpx
import pytest

from bc_auction.client import AuctionClient


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
