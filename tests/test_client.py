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
