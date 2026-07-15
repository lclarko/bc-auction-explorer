import argparse
import json
import re
import sys
from collections.abc import Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from bc_auction.client import AuctionClient
from bc_auction.errors import ParserContractError, ScraperError
from bc_auction.models import AuctionDetailRecord, SearchResultRecord
from bc_auction.parsers import (
    SearchPageTracker,
    parse_item_detail,
    parse_search_results,
    reconcile_search_result,
)

_SESSION_ID = re.compile(r"(?i)(sessionID=)[^&\s'\"<>]+")


def _positive_int(value: str) -> int:
    parsed_value = int(value)
    if parsed_value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed_value


def _collect_search_records(client: AuctionClient, limit: int) -> tuple[SearchResultRecord, ...]:
    page = client.search_open_auctions()
    tracker = SearchPageTracker()
    records: list[SearchResultRecord] = []
    visited_page_urls: set[str] = set()

    while len(records) < limit:
        if page.url in visited_page_urls:
            raise ParserContractError("search results repeated a page URL")
        visited_page_urls.add(page.url)

        results_page = parse_search_results(page.decode().text, page.url)
        tracker.add(results_page)
        records.extend(results_page.records[: limit - len(records)])

        if len(records) == limit or results_page.pagination is None:
            break
        next_page_url = results_page.pagination.next_page_url
        if next_page_url is None:
            break
        page = client.get(str(next_page_url))

    return tuple(records)


def scrape(
    client: AuctionClient,
    limit: int,
) -> tuple[list[AuctionDetailRecord], list[dict[str, str]]]:
    records: list[AuctionDetailRecord] = []
    failures: list[dict[str, str]] = []
    for search_result in _collect_search_records(client, limit):
        try:
            detail_page = client.get_item_detail(str(search_result.source_url))
            detail = parse_item_detail(detail_page.decode().text, detail_page.url)
            records.append(reconcile_search_result(search_result, detail))
        except (ScraperError, httpx.HTTPError, ValueError) as exc:
            failures.append(
                {
                    "source_id": search_result.source_id,
                    "source_url": _redact_url(str(search_result.source_url)),
                    "error": _redact_session_id(str(exc)),
                }
            )
    return records, failures


def _redact_url(value: str) -> str:
    parsed = urlsplit(value)
    query = urlencode(
        [
            (name, "REDACTED" if name.casefold() == "sessionid" else query_value)
            for name, query_value in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def _redact_session_id(value: str) -> str:
    return _SESSION_ID.sub(r"\1REDACTED", value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m bc_auction")
    commands = parser.add_subparsers(dest="command", required=True)
    scrape_command = commands.add_parser("scrape")
    scrape_command.add_argument("--limit", type=_positive_int, default=20)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command != "scrape":
        raise AssertionError(f"unsupported command: {args.command}")

    try:
        with AuctionClient() as client:
            records, failures = scrape(client, args.limit)
    except (ScraperError, httpx.HTTPError, ValueError) as exc:
        print(f"scrape failed: {_redact_session_id(str(exc))}", file=sys.stderr)
        return 1

    output = {
        "records": [
            {**record.model_dump(mode="json"), "source_url": _redact_url(str(record.source_url))}
            for record in records
        ],
        "failures": failures,
    }
    print(json.dumps(output, indent=2))
    if failures:
        print(f"{len(failures)} listing failures", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
