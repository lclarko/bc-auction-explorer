import json
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest

import bc_auction.__main__ as cli
from bc_auction.client import FetchedPage
from bc_auction.errors import ParserContractError
from bc_auction.persistence import (
    IdentityConflictError,
    PersistenceError,
    PersistResult,
    ScrapeRunStatus,
)

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


class _TwoRecordClient(_SuccessfulClient):
    _SOURCE_IDS: ClassVar[dict[str, str]] = {"8733643": "A277437", "8734455": "A277501"}

    def get_item_detail(self, source_url: str) -> FetchedPage:
        source_dis_id = parse_qs(urlparse(source_url).query)["disID"][0]
        source_id = self._SOURCE_IDS[source_dis_id]
        return FetchedPage(
            url=_DETAIL_URL,
            status_code=200,
            body=(_FIXTURES / "item-detail.html").read_bytes().replace(
                b"A277437",
                source_id.encode(),
            ),
            content_type="text/html; charset=utf-8",
            fetched_at=datetime.now(UTC),
        )


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


def test_persist_rejects_results_only_before_opening_the_source_client(capsys) -> None:
    exit_code = cli.main(["scrape", "--persist", "--results-only"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "scrape failed: --persist cannot be combined with --results-only\n"


def test_persist_requires_a_database_url_before_opening_the_source_client(
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.delenv("BC_AUCTION_DATABASE_URL", raising=False)

    exit_code = cli.main(["scrape", "--persist"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "requires --database-url or BC_AUCTION_DATABASE_URL" in captured.err


class _FakePersistenceRepository:
    run_id = UUID("00000000-0000-0000-0000-000000000001")

    def __init__(
        self,
        *,
        persist_error: bool = False,
        identity_conflict_at: int | None = None,
        finish_error: bool = False,
    ) -> None:
        self.persist_error = persist_error
        self.identity_conflict_at = identity_conflict_at
        self.finish_error = finish_error
        self.finished: list[tuple[ScrapeRunStatus, object]] = []
        self.started = False
        self.persist_calls = 0

    def ping(self) -> None:
        return None

    def start_scrape_run(self, *args: object, **kwargs: object) -> UUID:
        self.started = True
        return self.run_id

    def persist_reconciled_record(self, *args: object, **kwargs: object) -> PersistResult:
        self.persist_calls += 1
        if self.identity_conflict_at == self.persist_calls:
            raise IdentityConflictError("canonical auction identity belongs to another source ID")
        if self.persist_error:
            raise PersistenceError("database rejected auction persistence")
        return PersistResult(created=True, updated=False, observation_created=True)

    def finish_scrape_run(self, run_id: UUID, **kwargs: object) -> None:
        assert run_id == self.run_id
        self.finished.append((kwargs["status"], kwargs["counts"]))
        if self.finish_error:
            raise RuntimeError("database unavailable")


class _FakePersistenceEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def test_persist_creates_and_finishes_a_successful_scrape_run(monkeypatch, capsys) -> None:
    repository = _FakePersistenceRepository()
    monkeypatch.setattr(cli, "AuctionClient", _SuccessfulClient)
    monkeypatch.setattr(
        cli,
        "_open_repository",
        lambda _database_url: (repository, _FakePersistenceEngine()),
    )

    exit_code = cli.main(["scrape", "--limit", "1", "--persist", "--database-url", "postgresql://x"])

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert exit_code == 0
    assert output["persistence"] == {"scrape_run_id": str(repository.run_id)}
    assert repository.started is True
    assert repository.finished[0][0] is ScrapeRunStatus.SUCCEEDED
    assert repository.finished[0][1].observations_created == 1


def test_persist_marks_storage_failure_as_a_partial_run(monkeypatch, capsys) -> None:
    repository = _FakePersistenceRepository(persist_error=True)
    monkeypatch.setattr(cli, "AuctionClient", _SuccessfulClient)
    monkeypatch.setattr(
        cli,
        "_open_repository",
        lambda _database_url: (repository, _FakePersistenceEngine()),
    )

    exit_code = cli.main(["scrape", "--limit", "1", "--persist", "--database-url", "postgresql://x"])

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert exit_code == 2
    assert output["failures"][0]["error"] == "persistence failed"
    assert repository.finished[0][0] is ScrapeRunStatus.PARTIAL
    assert repository.finished[0][1].item_failures == 1


def test_persist_preserves_committed_counts_after_an_identity_conflict(monkeypatch, capsys) -> None:
    repository = _FakePersistenceRepository(identity_conflict_at=2)
    engine = _FakePersistenceEngine()
    monkeypatch.setattr(cli, "AuctionClient", _TwoRecordClient)
    monkeypatch.setattr(cli, "_open_repository", lambda _database_url: (repository, engine))

    exit_code = cli.main(["scrape", "--limit", "2", "--persist", "--database-url", "postgresql://x"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "persistence batch had an identity conflict" in captured.err
    assert repository.finished[0][0] is ScrapeRunStatus.FAILED
    assert repository.finished[0][1].items_created == 1
    assert repository.finished[0][1].observations_created == 1
    assert repository.finished[0][1].item_failures == 1
    assert engine.disposed is True


def test_failed_run_finalization_does_not_mask_the_scrape_error(monkeypatch, capsys) -> None:
    class FailingSearchClient(_SuccessfulClient):
        def search_open_auctions(
            self,
            *,
            keyword: str = "",
            display_order: str = "EndingFirst",
        ) -> FetchedPage:
            raise ParserContractError("invalid search results")

    repository = _FakePersistenceRepository(finish_error=True)
    engine = _FakePersistenceEngine()
    monkeypatch.setattr(cli, "AuctionClient", FailingSearchClient)
    monkeypatch.setattr(cli, "_open_repository", lambda _database_url: (repository, engine))

    exit_code = cli.main(["scrape", "--persist", "--database-url", "postgresql://x"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "scrape run finalization failed: RuntimeError" in captured.err
    assert "scrape failed: invalid search results" in captured.err
    assert repository.finished[0][0] is ScrapeRunStatus.FAILED
    assert repository.finished[0][1].items_created == 0
    assert repository.finished[0][1].observations_created == 0
    assert engine.disposed is True


def test_manual_scrape_writes_atomic_json_output(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "AuctionClient", _SuccessfulClient)
    output_path = tmp_path / "scrape.json"

    exit_code = cli.main(["scrape", "--limit", "1", "--output", str(output_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert json.loads(output_path.read_text(encoding="utf-8")) == json.loads(captured.out)
    assert list(tmp_path.glob(".scrape.json.*")) == []


def test_atomic_output_failure_preserves_the_existing_file(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "AuctionClient", _SuccessfulClient)
    output_path = tmp_path / "scrape.json"
    output_path.write_text("original output\n", encoding="utf-8")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("replacement failed")

    monkeypatch.setattr(cli.os, "replace", fail_replace)

    exit_code = cli.main(["scrape", "--limit", "1", "--output", str(output_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "replacement failed" in captured.err
    assert output_path.read_text(encoding="utf-8") == "original output\n"
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


def test_manual_scrape_reports_an_unavailable_detail(monkeypatch, capsys) -> None:
    class UnavailableDetailClient(_SuccessfulClient):
        def get_item_detail(self, source_url: str) -> FetchedPage:
            return _page("item-detail-unavailable.html", source_url, "text/html; charset=utf-8")

    monkeypatch.setattr(cli, "AuctionClient", UnavailableDetailClient)

    exit_code = cli.main(["scrape", "--limit", "1"])

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert exit_code == 2
    assert output["records"] == []
    assert output["failures"][0]["source_id"] == "A277437"
    assert "not a BC Auction item detail page" in output["failures"][0]["error"]
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
    collection = cli._collect_search_records(client, 31)

    assert len(collection.records) == 31
    assert collection.records[-1].source_id == "A277450"
    assert collection.pages_visited == 2
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
