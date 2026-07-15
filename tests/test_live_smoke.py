import json
from datetime import UTC, datetime
from pathlib import Path

import bc_auction.live_smoke as live_smoke
from bc_auction.client import FetchedPage

_FIXTURES = Path(__file__).parent / "fixtures"
_RESULTS_URL = "https://www.bcauction.ca/open.dll/submitDocSearch"
_DETAIL_URL = "https://www.bcauction.ca/open.dll/showDocSummary?sessionID=SESSION_ID&disID=8733643"


def _page(name: str, url: str) -> FetchedPage:
    return FetchedPage(
        url=url,
        status_code=200,
        body=(_FIXTURES / name).read_bytes(),
        content_type="text/html; charset=utf-8",
        fetched_at=datetime.now(UTC),
    )


def test_live_smoke_requires_an_explicit_environment_flag(monkeypatch, capsys) -> None:
    monkeypatch.delenv("BC_AUCTION_LIVE_SMOKE", raising=False)

    exit_code = live_smoke.main()

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == "live smoke requires BC_AUCTION_LIVE_SMOKE=1\n"


def test_live_smoke_reports_only_session_free_diagnostics(monkeypatch, capsys) -> None:
    class SmokeClient:
        detail_request_url: str | None = None

        def __enter__(self) -> "SmokeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def search_open_auctions(self) -> FetchedPage:
            return _page("results-open-page-1.html", _RESULTS_URL)

        def get_item_detail(self, request_url: str) -> FetchedPage:
            type(self).detail_request_url = request_url
            return _page("item-detail.html", _DETAIL_URL)

    monkeypatch.setenv("BC_AUCTION_LIVE_SMOKE", "1")
    monkeypatch.setattr(live_smoke, "AuctionClient", SmokeClient)

    exit_code = live_smoke.main()

    captured = capsys.readouterr()
    diagnostic = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert SmokeClient.detail_request_url is not None
    assert "sessionID=SESSION_ID" in SmokeClient.detail_request_url
    assert diagnostic["status"] == "ok"
    assert diagnostic["source_id"] == "A277437"
    assert "sessionID" not in diagnostic["canonical_source_url"]
    assert "SESSION_ID" not in captured.out
