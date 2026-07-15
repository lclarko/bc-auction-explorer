import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import bc_auction.__main__ as cli
from bc_auction.client import FetchedPage
from bc_auction.errors import ParserContractError

_FIXTURES = Path(__file__).parent / "fixtures"
_RESULTS_URL = "https://www.bcauction.ca/open.dll/submitDocSearch"
_DETAIL_URL = "https://www.bcauction.ca/open.dll/showDocSummary?sessionID=SESSION_ID&disID=8733643"


def _page(name: str, url: str, content_type: str | None = None) -> FetchedPage:
    return FetchedPage(
        url=url,
        status_code=200,
        body=(_FIXTURES / name).read_bytes(),
        content_type=content_type,
        fetched_at=datetime.now(UTC),
    )


class _SuccessfulClient:
    def __enter__(self) -> "_SuccessfulClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def search_open_auctions(
        self,
        *,
        keyword: str = "",
        display_order: str = "EndingFirst",
    ) -> FetchedPage:
        return _page("results-open-page-1.html", _RESULTS_URL, "text/html; charset=utf-8")

    def get_item_detail(self, source_url: str) -> FetchedPage:
        assert source_url.startswith("https://www.bcauction.ca/open.dll/showDisplayDocument?")
        return _page("item-detail.html", _DETAIL_URL)


def test_manual_scrape_prints_redacted_structured_output(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "AuctionClient", _SuccessfulClient)

    exit_code = cli.main(["scrape", "--limit", "1"])

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert output["summary"] == {
        "requested_limit": 1,
        "results_only": False,
        "keyword": "",
        "sort": "EndingFirst",
        "record_count": 1,
        "failure_count": 0,
    }
    assert output["failures"] == []
    assert output["records"][0]["source_id"] == "A277437"
    assert "sessionID" not in output["records"][0]["canonical_source_url"]
    assert "SESSION_ID" not in output["records"][0]["canonical_source_url"]
    assert "request_url" not in output["records"][0]


def test_manual_scrape_supports_results_only_keyword_and_sort(monkeypatch, capsys) -> None:
    class ResultsOnlyClient(_SuccessfulClient):
        requested_search: tuple[str, str] | None = None

        def search_open_auctions(
            self,
            *,
            keyword: str = "",
            display_order: str = "EndingFirst",
        ) -> FetchedPage:
            type(self).requested_search = (keyword, display_order)
            return super().search_open_auctions(keyword=keyword, display_order=display_order)

        def get_item_detail(self, source_url: str) -> FetchedPage:
            raise AssertionError("results-only scrape requested item detail")

    monkeypatch.setattr(cli, "AuctionClient", ResultsOnlyClient)

    exit_code = cli.main(
        ["scrape", "--limit", "1", "--results-only", "--keyword", "truck", "--sort", "HighestPrice"]
    )

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert ResultsOnlyClient.requested_search == ("truck", "HighestPrice")
    assert output["summary"]["results_only"] is True
    assert output["summary"]["keyword"] == "truck"
    assert output["summary"]["sort"] == "HighestPrice"
    assert output["failures"] == []
    assert "content_hash" not in output["records"][0]


def test_manual_scrape_writes_atomic_json_output(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "AuctionClient", _SuccessfulClient)
    output_path = tmp_path / "scrape.json"

    exit_code = cli.main(["scrape", "--limit", "1", "--output", str(output_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert json.loads(output_path.read_text(encoding="utf-8")) == json.loads(captured.out)
    assert list(tmp_path.glob(".scrape.json.*")) == []


def test_manual_scrape_reports_detail_parser_failures(monkeypatch, capsys) -> None:
    class FailingClient(_SuccessfulClient):
        def get_item_detail(self, source_url: str) -> FetchedPage:
            return FetchedPage(
                url=source_url,
                status_code=200,
                body=b"<html><body>invalid response</body></html>",
                content_type="text/html",
                fetched_at=datetime.now(UTC),
            )

    monkeypatch.setattr(cli, "AuctionClient", FailingClient)

    exit_code = cli.main(["scrape", "--limit", "1"])

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert exit_code == 2
    assert output["records"] == []
    assert output["failures"][0]["source_id"] == "A277437"
    assert "document title" in output["failures"][0]["error"]
    assert captured.err == "1 listing failures\n"


def test_collect_search_records_follows_pagination() -> None:
    class PaginatedClient(_SuccessfulClient):
        def __init__(self) -> None:
            self.requested_urls: list[str] = []

        def get(self, page_url: str) -> FetchedPage:
            self.requested_urls.append(page_url)
            return _page(
                "results-open-page-2.html",
                page_url,
                "text/html; charset=utf-8",
            )

    client = PaginatedClient()
    records = cli._collect_search_records(client, 31)

    assert len(records) == 31
    assert records[-1].source_id == "A277450"
    assert len(client.requested_urls) == 1


def test_manual_scrape_returns_one_when_search_enumeration_fails(monkeypatch, capsys) -> None:
    class FailingSearchClient(_SuccessfulClient):
        def search_open_auctions(
            self,
            *,
            keyword: str = "",
            display_order: str = "EndingFirst",
        ) -> FetchedPage:
            raise ParserContractError("invalid search results")

    monkeypatch.setattr(cli, "AuctionClient", FailingSearchClient)

    exit_code = cli.main(["scrape", "--limit", "1"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "scrape failed: invalid search results\n"


def test_collect_search_records_enforces_the_maximum_page_limit(monkeypatch) -> None:
    class PaginatedClient(_SuccessfulClient):
        def __init__(self) -> None:
            self.requested_urls: list[str] = []

        def get(self, page_url: str) -> FetchedPage:
            self.requested_urls.append(page_url)
            return _page(
                "results-open-page-2.html",
                page_url,
                "text/html; charset=utf-8",
            )

    monkeypatch.setattr(cli, "_MAX_SEARCH_PAGES", 1)
    client = PaginatedClient()

    with pytest.raises(ParserContractError, match="maximum page limit"):
        cli._collect_search_records(client, 31)

    assert client.requested_urls == []


def test_collect_search_records_rejects_pagination_regression() -> None:
    class RegressingClient(_SuccessfulClient):
        def get(self, page_url: str) -> FetchedPage:
            return _page(
                "results-open-page-1.html",
                page_url,
                "text/html; charset=utf-8",
            )

    with pytest.raises(ParserContractError, match="did not advance to a later page"):
        cli._collect_search_records(RegressingClient(), 31)
