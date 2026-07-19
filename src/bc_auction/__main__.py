from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TextIO, cast
from uuid import UUID

import httpx
from tqdm import tqdm

from bc_auction.client import AuctionClient, FetchedPage
from bc_auction.errors import ParserContractError, ScraperError
from bc_auction.models import AuctionDetailRecord, SearchResultRecord
from bc_auction.parsers import (
    SearchPageTracker,
    parse_item_detail,
    parse_search_results,
    reconcile_search_result,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from bc_auction.persistence import (
        AuctionRepository,
        PersistResult,
        ScrapeRunCounts,
        ScrapeRunCoverage,
        ScrapeRunInput,
        ScrapeRunMetrics,
    )

_SESSION_ID = re.compile(r"(?i)(sessionID=)[^&\s'\"<>]+")
_MAX_SEARCH_PAGES = 100
_ScrapeRecord = SearchResultRecord | AuctionDetailRecord
_PARSER_VERSION = "ms2-v1"


@dataclass(frozen=True, slots=True)
class _SearchCollection:
    records: tuple[SearchResultRecord, ...]
    pages_visited: int
    expected_product_groups: int = 0
    processed_product_groups: int = 0
    duplicate_listings: int = 0
    enumeration_complete: bool = False


@dataclass(frozen=True, slots=True)
class _ScrapeOutcome:
    records: list[_ScrapeRecord]
    failures: list[dict[str, str]]
    pages_visited: int
    items_seen: int
    expected_product_groups: int = 0
    processed_product_groups: int = 0
    duplicate_listings: int = 0
    enumeration_complete: bool = False


class _ProgressBar(Protocol):
    total: float | None
    n: float

    def close(self) -> None: ...

    def set_postfix_str(self, s: str = "", refresh: bool = True) -> None: ...

    def update(self, n: float = 1) -> bool: ...


class _ScrapeProgress(Protocol):
    def start_search(self) -> None: ...

    def start_search_groups(self, total: int) -> None: ...

    def advance_search_group(self, *, unique_listings: int, pages_visited: int) -> None: ...

    def finish_search(self, *, unique_listings: int, pages_visited: int) -> None: ...

    def start_details(self, total: int) -> None: ...

    def advance_detail(self, *, failures: int) -> None: ...

    def finish_details(self, *, successful: int, failures: int) -> None: ...

    def start_persistence(self, total: int) -> None: ...

    def advance_persistence(self, *, created: int, updated: int, failures: int) -> None: ...

    def finish_persistence(self, *, created: int, updated: int, failures: int) -> None: ...

    def close(self) -> None: ...


class _TerminalScrapeProgress:
    """Render compact scrape progress to an interactive terminal's stderr."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._bar: _ProgressBar | None = None

    def start_search(self) -> None:
        print("Preparing public auction search...", file=self._stream, flush=True)

    def start_search_groups(self, total: int) -> None:
        self._start_bar(total, "Enumerating product groups", "group")

    def advance_search_group(self, *, unique_listings: int, pages_visited: int) -> None:
        self._advance(f"{unique_listings} unique, {pages_visited} pages")

    def finish_search(self, *, unique_listings: int, pages_visited: int) -> None:
        self._finish_bar(f"{unique_listings} unique, {pages_visited} pages")

    def start_details(self, total: int) -> None:
        self._start_bar(total, "Fetching listing details", "listing")

    def advance_detail(self, *, failures: int) -> None:
        self._advance(f"{failures} failed")

    def finish_details(self, *, successful: int, failures: int) -> None:
        self._finish_bar(f"{successful} complete, {failures} failed")

    def start_persistence(self, total: int) -> None:
        self._start_bar(total, "Saving listing observations", "listing")

    def advance_persistence(self, *, created: int, updated: int, failures: int) -> None:
        self._advance(f"{created} created, {updated} updated, {failures} failed")

    def finish_persistence(self, *, created: int, updated: int, failures: int) -> None:
        self._finish_bar(f"{created} created, {updated} updated, {failures} failed")

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()
            self._bar = None

    def _start_bar(self, total: int, description: str, unit: str) -> None:
        self.close()
        self._bar = cast(
            _ProgressBar,
            tqdm(
                total=total,
                desc=description,
                unit=unit,
                dynamic_ncols=True,
                file=self._stream,
            ),
        )

    def _advance(self, postfix: str) -> None:
        if self._bar is None:
            return
        self._bar.update()
        self._bar.set_postfix_str(postfix)

    def _finish_bar(self, postfix: str) -> None:
        if self._bar is None:
            return
        self._bar.set_postfix_str(postfix)
        if self._bar.total is not None and self._bar.n < self._bar.total:
            self._bar.total = self._bar.n
        self.close()


def _create_progress_reporter(stream: TextIO) -> _ScrapeProgress | None:
    if not stream.isatty():
        return None
    return _TerminalScrapeProgress(stream)


class _PersistenceBatchFailure(RuntimeError):
    def __init__(
        self,
        results: list[PersistResult],
        failures: list[dict[str, str]],
    ) -> None:
        super().__init__("persistence batch had an identity conflict")
        self.results = results
        self.failures = failures


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
    progress: _ScrapeProgress | None = None,
) -> _SearchCollection:
    if progress is not None:
        progress.start_search()
    search = client.prepare_open_auction_search()
    if progress is not None:
        progress.start_search_groups(len(search.product_groups))
    records: list[SearchResultRecord] = []
    records_by_source_id: dict[str, SearchResultRecord] = {}
    records_by_canonical_url: dict[str, SearchResultRecord] = {}
    pages_visited = 0
    duplicate_listings = 0
    processed_product_groups = 0
    truncated = False

    def add_search_record(record: SearchResultRecord) -> bool:
        nonlocal duplicate_listings
        added = _add_unique_search_record(
            record,
            records,
            records_by_source_id,
            records_by_canonical_url,
        )
        if not added:
            duplicate_listings += 1
        return len(records) >= limit

    for product_group in search.product_groups:
        if len(records) >= limit:
            truncated = True
            break
        page = client.search_product_group(
            product_group,
            keyword=keyword,
            display_order=display_order,
        )
        group_collection = _collect_search_records_from_page(
            client,
            page,
            on_record=add_search_record,
        )
        pages_visited += group_collection.pages_visited
        processed_product_groups += 1
        if len(records) >= limit:
            # The collector stops as soon as the cap is reached, so it cannot
            # prove that the remaining source pages and groups were exhausted.
            truncated = True
        if progress is not None:
            progress.advance_search_group(
                unique_listings=len(records),
                pages_visited=pages_visited,
            )

    return _SearchCollection(
        records=tuple(records[:limit]),
        pages_visited=pages_visited,
        expected_product_groups=len(search.product_groups),
        processed_product_groups=processed_product_groups,
        duplicate_listings=duplicate_listings,
        enumeration_complete=(
            not truncated and processed_product_groups == len(search.product_groups)
        ),
    )


def _collect_search_records_from_page(
    client: AuctionClient,
    page: FetchedPage,
    limit: int | None = None,
    *,
    on_record: Callable[[SearchResultRecord], bool] | None = None,
) -> _SearchCollection:
    tracker = SearchPageTracker()
    records: list[SearchResultRecord] = []
    visited_page_urls: set[str] = set()
    pages_seen = 0
    previous_page_number: int | None = None
    previous_record_end: int | None = None

    while limit is None or len(records) < limit:
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
        for record in results_page.records:
            if limit is not None and len(records) >= limit:
                break
            records.append(record)
            if on_record is not None and on_record(record):
                return _SearchCollection(records=tuple(records), pages_visited=pages_seen)

        if (limit is not None and len(records) == limit) or pagination is None:
            break
        next_request_url = pagination.next_request_url
        if next_request_url is None:
            break
        if pages_seen >= _MAX_SEARCH_PAGES:
            raise ParserContractError("search results exceeded the maximum page limit")
        page = client.get(str(next_request_url))

    return _SearchCollection(records=tuple(records), pages_visited=pages_seen)


def _add_unique_search_record(
    record: SearchResultRecord,
    records: list[SearchResultRecord],
    records_by_source_id: dict[str, SearchResultRecord],
    records_by_canonical_url: dict[str, SearchResultRecord],
) -> bool:
    existing_source_id = records_by_source_id.get(record.source_id)
    canonical_url = str(record.canonical_source_url)
    existing_canonical_url = records_by_canonical_url.get(canonical_url)
    if existing_source_id is not None and (
        existing_source_id.canonical_source_url != record.canonical_source_url
    ):
        raise ParserContractError("product groups disagreed about a source ID's canonical URL")
    if existing_canonical_url is not None and existing_canonical_url.source_id != record.source_id:
        raise ParserContractError("product groups reused a canonical URL for different source IDs")
    if existing_source_id is not None or existing_canonical_url is not None:
        return False
    records.append(record)
    records_by_source_id[record.source_id] = record
    records_by_canonical_url[canonical_url] = record
    return True


def scrape(
    client: AuctionClient,
    limit: int,
    *,
    keyword: str = "",
    display_order: str = "EndingFirst",
    results_only: bool = False,
    progress: _ScrapeProgress | None = None,
) -> tuple[list[_ScrapeRecord], list[dict[str, str]]]:
    outcome = _scrape_with_outcome(
        client,
        limit,
        keyword=keyword,
        display_order=display_order,
        results_only=results_only,
        progress=progress,
    )
    return outcome.records, outcome.failures


def _scrape_with_outcome(
    client: AuctionClient,
    limit: int,
    *,
    keyword: str = "",
    display_order: str = "EndingFirst",
    results_only: bool = False,
    progress: _ScrapeProgress | None = None,
) -> _ScrapeOutcome:
    search_records = _collect_search_records(
        client,
        limit,
        keyword=keyword,
        display_order=display_order,
        progress=progress,
    )
    if progress is not None:
        progress.finish_search(
            unique_listings=len(search_records.records),
            pages_visited=search_records.pages_visited,
        )
    if results_only:
        return _ScrapeOutcome(
            records=list(search_records.records),
            failures=[],
            pages_visited=search_records.pages_visited,
            items_seen=len(search_records.records),
            expected_product_groups=search_records.expected_product_groups,
            processed_product_groups=search_records.processed_product_groups,
            duplicate_listings=search_records.duplicate_listings,
            enumeration_complete=search_records.enumeration_complete,
        )

    records: list[_ScrapeRecord] = []
    failures: list[dict[str, str]] = []
    if progress is not None:
        progress.start_details(len(search_records.records))
    for search_result in search_records.records:
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
        finally:
            if progress is not None:
                progress.advance_detail(failures=len(failures))
    if progress is not None:
        progress.finish_details(successful=len(records), failures=len(failures))
    return _ScrapeOutcome(
        records=records,
        failures=failures,
        pages_visited=search_records.pages_visited,
        items_seen=len(search_records.records),
        expected_product_groups=search_records.expected_product_groups,
        processed_product_groups=search_records.processed_product_groups,
        duplicate_listings=search_records.duplicate_listings,
        enumeration_complete=search_records.enumeration_complete,
    )


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
    scrape_command.add_argument("--persist", action="store_true")
    scrape_command.add_argument("--database-url")
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

    repository: AuctionRepository | None = None
    engine: Engine | None = None
    run_id: UUID | None = None
    outcome: _ScrapeOutcome | None = None
    counts: ScrapeRunCounts | None = None
    coverage: ScrapeRunCoverage | None = None
    metrics: ScrapeRunMetrics | None = None
    progress = _create_progress_reporter(sys.stderr)
    run_finished = False
    try:
        if args.persist and args.results_only:
            raise ValueError("--persist cannot be combined with --results-only")
        if args.persist:
            repository, engine = _open_repository(args.database_url)
            repository.ping()
            run_id = repository.start_scrape_run(
                _scrape_run_input(args),
                started_at=datetime.now(UTC),
            )
        with AuctionClient() as client:
            try:
                outcome = _scrape_with_outcome(
                    client,
                    args.limit,
                    keyword=args.keyword,
                    display_order=args.display_order,
                    results_only=args.results_only,
                    progress=progress,
                )
            finally:
                metrics = _scrape_run_metrics(client) if args.persist else None
        records = outcome.records
        failures = outcome.failures
        coverage = _scrape_run_coverage(outcome, (), 0)
        if repository is not None and run_id is not None:
            _validate_persistence_batch(records)
            try:
                persistence_results, persistence_failures = _persist_records(
                    repository,
                    run_id,
                    records,
                    progress=progress,
                )
            except _PersistenceBatchFailure as exc:
                failures.extend(exc.failures)
                counts = _scrape_run_counts(outcome, exc.results, len(failures))
                coverage = _scrape_run_coverage(outcome, exc.results, len(exc.failures))
                raise
            failures.extend(persistence_failures)
            counts = _scrape_run_counts(outcome, persistence_results, len(failures))
            coverage = _scrape_run_coverage(
                outcome,
                persistence_results,
                len(persistence_failures),
            )
            from bc_auction.persistence import ScrapeRunStatus

            repository.finish_scrape_run(
                run_id,
                status=ScrapeRunStatus.PARTIAL if failures else ScrapeRunStatus.SUCCEEDED,
                counts=counts,
                metrics=metrics,
                coverage=coverage,
                persisted_source_ids=[record.source_id for record in records],
            )
            run_finished = True
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
        if run_id is not None:
            output["persistence"] = {"scrape_run_id": str(run_id)}
        _write_output(args.output, output)
    except (OSError, ScraperError, httpx.HTTPError, ValueError) as exc:
        if progress is not None:
            progress.close()
        _report_failed_run_finalization(
            repository, run_id, outcome, counts, coverage, metrics, run_finished
        )
        print(f"scrape failed: {_redact_session_id(str(exc))}", file=sys.stderr)
        return 1
    except Exception as exc:
        if progress is not None:
            progress.close()
        _report_failed_run_finalization(
            repository, run_id, outcome, counts, coverage, metrics, run_finished
        )
        print(f"scrape failed: {_redact_session_id(str(exc))}", file=sys.stderr)
        return 1
    finally:
        if progress is not None:
            progress.close()
        if engine is not None:
            engine.dispose()

    if failures:
        print(f"{len(failures)} listing failures", file=sys.stderr)
        return 2
    return 0


def _open_repository(database_url: str | None) -> tuple[AuctionRepository, Engine]:
    from bc_auction.database import create_postgres_engine
    from bc_auction.persistence import AuctionRepository

    resolved_url = database_url or os.environ.get("BC_AUCTION_DATABASE_URL")
    if not resolved_url:
        raise ValueError("persistence requires --database-url or BC_AUCTION_DATABASE_URL")
    engine = create_postgres_engine(resolved_url)
    return AuctionRepository(engine), engine


def _scrape_run_input(args: argparse.Namespace) -> ScrapeRunInput:
    from bc_auction.persistence import ScrapeRunInput

    return ScrapeRunInput(
        requested_limit=args.limit,
        keyword=args.keyword,
        sort=args.display_order,
        parser_version=_PARSER_VERSION,
    )


def _validate_persistence_batch(records: Sequence[_ScrapeRecord]) -> None:
    source_ids = [record.source_id for record in records]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("persistence batch contained duplicate source IDs")
    canonical_urls = [str(record.canonical_source_url) for record in records]
    if len(canonical_urls) != len(set(canonical_urls)):
        raise ValueError("persistence batch contained duplicate canonical source URLs")


def _persist_records(
    repository: AuctionRepository,
    run_id: UUID,
    records: Sequence[_ScrapeRecord],
    *,
    progress: _ScrapeProgress | None = None,
) -> tuple[list[PersistResult], list[dict[str, str]]]:
    from bc_auction.persistence import (
        IdentityConflictError,
        PersistenceError,
        convert_reconciled_record,
    )

    results: list[PersistResult] = []
    failures: list[dict[str, str]] = []
    created = 0
    updated = 0
    if progress is not None:
        progress.start_persistence(len(records))
    for record in records:
        if not isinstance(record, AuctionDetailRecord):
            raise ValueError("persistence requires detail-complete records")
        try:
            persisted_record = convert_reconciled_record(record, observed_at=datetime.now(UTC))
            result = repository.persist_reconciled_record(run_id, persisted_record)
            results.append(result)
            created += result.created
            updated += result.updated
        except IdentityConflictError:
            failures.append(
                {
                    "source_id": record.source_id,
                    "canonical_source_url": str(record.canonical_source_url),
                    "error": "persistence identity conflict",
                }
            )
            raise _PersistenceBatchFailure(results, failures) from None
        except PersistenceError:
            failures.append(
                {
                    "source_id": record.source_id,
                    "canonical_source_url": str(record.canonical_source_url),
                    "error": "persistence failed",
                }
            )
        finally:
            if progress is not None:
                progress.advance_persistence(
                    created=created,
                    updated=updated,
                    failures=len(failures),
                )
    if progress is not None:
        progress.finish_persistence(created=created, updated=updated, failures=len(failures))
    return results, failures


def _scrape_run_counts(
    outcome: _ScrapeOutcome,
    results: Sequence[PersistResult],
    item_failures: int,
) -> ScrapeRunCounts:
    from bc_auction.persistence import ScrapeRunCounts

    return ScrapeRunCounts(
        pages_visited=outcome.pages_visited,
        items_seen=outcome.items_seen,
        items_created=sum(result.created for result in results),
        items_updated=sum(result.updated for result in results),
        observations_created=sum(result.observation_created for result in results),
        item_failures=item_failures,
    )


def _scrape_run_coverage(
    outcome: _ScrapeOutcome,
    results: Sequence[PersistResult],
    persistence_failures: int,
) -> ScrapeRunCoverage:
    from bc_auction.persistence import ScrapeRunCoverage

    return ScrapeRunCoverage(
        expected_product_groups=outcome.expected_product_groups,
        processed_product_groups=outcome.processed_product_groups,
        unique_listings_enumerated=outcome.items_seen,
        duplicate_listings_enumerated=outcome.duplicate_listings,
        detail_attempted=outcome.items_seen,
        detail_succeeded=len(outcome.records),
        persistence_succeeded=len(results),
        persistence_failures=persistence_failures,
        enumeration_complete=outcome.enumeration_complete,
    )


def _scrape_run_metrics(client: AuctionClient) -> ScrapeRunMetrics:
    from bc_auction.persistence import ScrapeRunMetrics

    metrics = client.metrics
    return ScrapeRunMetrics(
        source_requests=metrics.requests_attempted,
        source_responses=metrics.responses_received,
        source_retries=metrics.retries,
        rate_limit_responses=metrics.rate_limit_responses,
        source_transport_errors=metrics.transport_errors,
        source_request_duration_ms=metrics.request_duration_ms,
        source_request_wait_duration_ms=metrics.request_wait_duration_ms,
        source_retry_wait_duration_ms=metrics.retry_wait_duration_ms,
    )


def _report_failed_run_finalization(
    repository: AuctionRepository | None,
    run_id: UUID | None,
    outcome: _ScrapeOutcome | None,
    counts: ScrapeRunCounts | None,
    coverage: ScrapeRunCoverage | None,
    metrics: ScrapeRunMetrics | None,
    run_finished: bool,
) -> None:
    if repository is None or run_id is None or run_finished:
        return
    finalization_error = _finish_failed_run(repository, run_id, outcome, counts, coverage, metrics)
    if finalization_error is not None:
        print(f"scrape run finalization failed: {finalization_error}", file=sys.stderr)


def _finish_failed_run(
    repository: AuctionRepository,
    run_id: UUID,
    outcome: _ScrapeOutcome | None,
    counts: ScrapeRunCounts | None,
    coverage: ScrapeRunCoverage | None,
    metrics: ScrapeRunMetrics | None,
) -> str | None:
    from bc_auction.persistence import ScrapeRunCounts, ScrapeRunStatus

    try:
        repository.finish_scrape_run(
            run_id,
            status=ScrapeRunStatus.FAILED,
            counts=counts
            or ScrapeRunCounts(
                pages_visited=outcome.pages_visited if outcome is not None else 0,
                items_seen=outcome.items_seen if outcome is not None else 0,
                items_created=0,
                items_updated=0,
                observations_created=0,
                item_failures=len(outcome.failures) if outcome is not None else 0,
            ),
            coverage=coverage,
            metrics=metrics,
            error_summary="scrape failed",
        )
    except Exception as exc:
        return type(exc).__name__
    return None


if __name__ == "__main__":
    raise SystemExit(main())
