import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

import bc_auction.__main__ as cli
from bc_auction.client import AuctionClient
from bc_auction.parsers.results import parse_search_results

_FIXTURES = Path(__file__).parent / "fixtures"
_BASE_URL = "https://www.bcauction.ca"
_SESSION_ID = "MOCK_SESSION_VALUE_MUST_NOT_LEAK"
_SESSION_COOKIE = f"sessionID=|{_SESSION_ID}|"
_DETAIL_TEMPLATE_ID = b"8733643"
_DETAIL_TEMPLATE_SOURCE_ID = b"A277437"
_DETAIL_TEMPLATE_TITLE = b"Sanitized vehicle listing"


def _fixture(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes().replace(b"SESSION_ID", _SESSION_ID.encode())


def _detail_records_by_dis_id() -> dict[str, str]:
    records = []
    for fixture_name in ("results-open-page-1.html", "results-open-page-2.html"):
        page = parse_search_results(
            _fixture(fixture_name).decode("utf-8"),
            f"{_BASE_URL}/open.dll/submitDocSearch",
        )
        records.extend(page.records)

    records = records[:31]
    assert len(records) == 31
    records_by_dis_id = {
        parse_qs(urlparse(str(record.request_url)).query)["disID"][0]: record.source_id
        for record in records
    }
    closed_record = parse_search_results(
        _fixture("results-closed.html").decode("utf-8"),
        f"{_BASE_URL}/open.dll/submitDocSearch",
    ).records[0]
    records_by_dis_id["999"] = closed_record.source_id
    return records_by_dis_id


def _detail_fixture(dis_id: str, source_id: str) -> bytes:
    return (
        _fixture("item-detail.html")
        .replace(_DETAIL_TEMPLATE_ID, dis_id.encode())
        .replace(_DETAIL_TEMPLATE_SOURCE_ID, source_id.encode())
        .replace(_DETAIL_TEMPLATE_TITLE, f"Mock detail for {source_id}".encode())
    )


def _working_dis_id(request: httpx.Request) -> str:
    redirect = request.url.params.get("redirect")
    assert redirect is not None
    values = parse_qs(redirect.replace("^||^", "&"))
    dis_ids = values.get("disID")
    assert dis_ids is not None
    assert len(dis_ids) == 1
    return dis_ids[0]


def test_scrape_cli_runs_the_full_mocked_flow_without_serializing_session_data(
    monkeypatch, capsys
) -> None:
    detail_records = _detail_records_by_dis_id()
    requested_paths: list[str] = []
    submitted_product_groups: list[dict[str, list[str]]] = []

    def html_response(request: httpx.Request, body: bytes) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/html; charset=utf-8"},
            request=request,
        )

    def require_session(request: httpx.Request, *, in_query: bool = True) -> None:
        assert request.headers.get("cookie") == _SESSION_COOKIE
        if in_query:
            assert request.url.params.get("sessionID") == _SESSION_ID

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.bcauction.ca"
        requested_paths.append(request.url.path)

        if request.url.path == "/open.dll/welcome":
            assert request.method == "GET"
            assert request.url.params == httpx.QueryParams({"language": "En"})
            return html_response(request, _fixture("welcome.html"))

        if request.url.path == "/open.dll/showWelcomeContent":
            assert request.method == "GET"
            require_session(request)
            return html_response(request, _fixture("welcome-content.html"))

        if request.url.path == "/open.dll/submitLogin":
            assert request.method == "GET"
            require_session(request)
            return httpx.Response(
                302,
                headers={"location": f"/open.dll/showDocumentSearch?sessionID={_SESSION_ID}"},
                request=request,
            )

        if request.url.path == "/open.dll/showDocumentSearch":
            assert request.method == "GET"
            require_session(request)
            return html_response(request, _fixture("search-entry.html"))

        if request.url.path == "/open.dll/submitDocSearch":
            require_session(request, in_query=request.method == "GET")
            if request.method == "POST":
                fields = parse_qs(request.content.decode(), keep_blank_values=True)
                submitted_product_groups.append(fields)
                assert fields["sessionID"] == [_SESSION_ID]
                assert fields["display_order"] == ["EndingFirst"]
                if fields["productDisID"] == ["5810716"]:
                    assert fields["productDesc"] == ["Antiques and Collectibles"]
                    return html_response(request, _fixture("results-closed.html"))
                if fields["productDisID"] == ["4460126"]:
                    assert fields["productDesc"] == ["Art / Photography / Music"]
                    return html_response(request, _fixture("results-open-page-1.html"))
                raise AssertionError(f"unexpected product group: {fields['productDisID']}")

            assert request.method == "GET"
            assert request.url.params.get("currentPage") == "2"
            assert request.url.params.get("recordNum") == "31"
            return html_response(request, _fixture("results-open-page-2.html"))

        if request.url.path == "/open.dll/showDisplayDocument":
            assert request.method == "GET"
            require_session(request)
            dis_id = request.url.params.get("disID")
            assert dis_id in detail_records
            return html_response(
                request,
                _fixture("item-detail-frame.html").replace(_DETAIL_TEMPLATE_ID, dis_id.encode()),
            )

        if request.url.path == "/open.dll/showWorking":
            assert request.method == "GET"
            require_session(request)
            dis_id = _working_dis_id(request)
            assert dis_id in detail_records
            return html_response(
                request,
                _fixture("item-detail-working.html").replace(_DETAIL_TEMPLATE_ID, dis_id.encode()),
            )

        if request.url.path == "/open.dll/showDocSummary":
            assert request.method == "GET"
            require_session(request)
            dis_id = request.url.params.get("disID")
            assert dis_id in detail_records
            return html_response(request, _detail_fixture(dis_id, detail_records[dis_id]))

        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    monkeypatch.setattr(
        cli,
        "AuctionClient",
        lambda: AuctionClient(min_request_interval=0, transport=httpx.MockTransport(handler)),
    )

    exit_code = cli.main(["scrape", "--limit", "2"])

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert output["failures"] == []
    assert len(output["records"]) == 2
    assert output["records"][0]["source_id"] == "A000001"
    assert output["records"][-1]["source_id"] == "A277437"
    assert output["records"][0]["title"] == "Mock detail for A000001"
    assert "request_url" not in output["records"][0]
    assert all("canonical_source_url" in record for record in output["records"])
    assert all("sessionID" not in record["canonical_source_url"] for record in output["records"])
    assert "sessionID" not in captured.out
    assert _SESSION_ID not in captured.out
    assert requested_paths[:6] == [
        "/open.dll/welcome",
        "/open.dll/showWelcomeContent",
        "/open.dll/submitLogin",
        "/open.dll/showDocumentSearch",
        "/open.dll/submitDocSearch",
        "/open.dll/submitDocSearch",
    ]
    assert [fields["productDisID"] for fields in submitted_product_groups] == [
        ["5810716"],
        ["4460126"],
    ]
    assert requested_paths.count("/open.dll/showDisplayDocument") == 2
    assert requested_paths.count("/open.dll/showWorking") == 2
    assert requested_paths.count("/open.dll/showDocSummary") == 2
