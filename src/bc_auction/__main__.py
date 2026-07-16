import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

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
_MAX_SEARCH_PAGES = 100
_ScrapeRecord = SearchResultRecord | AuctionDetailRecord


def _positive_int(value: str) -> int:
    parsed_value = int(value)
    if parsed_value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed_value


def _collect_search_records(
    client: AuctionClient,
    limit: int,
    *,
    keyword: str = "",
    display_order: str = "EndingFirst",
) -> tuple[SearchResultRecord, ...]:
    page = client.search_open_auctions(keyword=keyword, display_order=display_order)
    tracker = SearchPageTracker()
    records: list[SearchResultRecord] = []
    visited_page_urls: set[str] = set()
    pages_seen = 0
    previous_page_number: int | None = None
    previous_record_end: int | None = None

    while len(records) < limit:
        if pages_seen >= _MAX_SEARCH_PAGES:
            raise ParserContractError("search results exceeded the maximum page limit")
        if page.url in visited_page_urls:
            raise ParserContractError("search results repeated a page URL")
        visited_page_urls.add(page.url)

        results_page = parse_search_results(page.decode().text, page.url)
        pages_seen += 1
        pagination = results_page.pagination
        if pagination is not None:
            if previous_page_number is not None and pagination.current_page <= previous_page_number:
                raise ParserContractError("search results did not advance to a later page")
            if previous_record_end is not None and pagination.record_start <= previous_record_end:
                raise ParserContractError("search results did not advance to later records")
            previous_page_number = pagination.current_page
            previous_record_end = pagination.record_end
        tracker.add(results_page)
        records.extend(results_page.records[: limit - len(records)])

        if len(records) == limit or pagination is None:
            break
        next_request_url = pagination.next_request_url
        if next_request_url is None:
            break
        if pages_seen >= _MAX_SEARCH_PAGES:
            raise ParserContractError("search results exceeded the maximum page limit")
        page = client.get(str(next_request_url))

    return tuple(records)


def scrape(
    client: AuctionClient,
    limit: int,
    *,
    keyword: str = "",
    display_order: str = "EndingFirst",
    results_only: bool = False,
) -> tuple[list[_ScrapeRecord], list[dict[str, str]]]:
    search_records = _collect_search_records(
        client,
        limit,
        keyword=keyword,
        display_order=display_order,
    )
    if results_only:
        return list(search_records), []

    records: list[_ScrapeRecord] = []
    failures: list[dict[str, str]] = []
    for search_result in search_records:
        try:
            detail_page = client.get_item_detail(str(search_result.request_url))
            detail = parse_item_detail(detail_page.decode().text, detail_page.url)
            records.append(reconcile_search_result(search_result, detail))
        except (ScraperError, httpx.HTTPError, ValueError) as exc:
            failures.append(
                {
                    "source_id": search_result.source_id,
                    "canonical_source_url": str(search_result.canonical_source_url),
                    "error": _redact_session_id(str(exc)),
                }
            )
    return records, failures


def _redact_session_id(value: str) -> str:
    return _SESSION_ID.sub(r"\1REDACTED", value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m bc_auction")
    commands = parser.add_subparsers(dest="command", required=True)
    scrape_command = commands.add_parser("scrape")
    scrape_command.add_argument("--limit", type=_positive_int, default=20)
    scrape_command.add_argument("--output", type=Path)
    scrape_command.add_argument("--results-only", action="store_true")
    scrape_command.add_argument("--keyword", default="")
    scrape_command.add_argument("--sort", dest="display_order", default="EndingFirst")
    return parser


def _write_output(output_path: Path | None, output: Mapping[str, object]) -> None:
    serialized = json.dumps(output, indent=2)
    if output_path is not None:
        _write_output_atomically(output_path, serialized)
    print(serialized)


def _write_output_atomically(output_path: Path, serialized: str) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(f"{serialized}\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, output_path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command != "scrape":
        raise AssertionError(f"unsupported command: {args.command}")

    try:
        with AuctionClient() as client:
            records, failures = scrape(
                client,
                args.limit,
                keyword=args.keyword,
                display_order=args.display_order,
                results_only=args.results_only,
            )
        output = {
            "summary": {
                "requested_limit": args.limit,
                "results_only": args.results_only,
                "keyword": args.keyword,
                "sort": args.display_order,
                "record_count": len(records),
                "failure_count": len(failures),
            },
            "records": [record.model_dump(mode="json") for record in records],
            "failures": failures,
        }
        _write_output(args.output, output)
    except (OSError, ScraperError, httpx.HTTPError, ValueError) as exc:
        print(f"scrape failed: {_redact_session_id(str(exc))}", file=sys.stderr)
        return 1

    if failures:
        print(f"{len(failures)} listing failures", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
