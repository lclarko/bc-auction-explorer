"""Read-only SQL queries for the public auction API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.engine import Engine, RowMapping
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from bc_auction.api_models import (
    Facet,
    FacetList,
    ListingAvailability,
    ListingDetail,
    ListingPage,
    ListingSort,
    ListingSummary,
    ListingView,
    PageInfo,
    ScrapeRunSummary,
    ScrapeStatus,
)
from bc_auction.database import auction_items, item_observations, scrape_runs
from bc_auction.models import AuctionStatus


@dataclass(frozen=True, slots=True)
class ListingFilters:
    keyword: str | None
    location: str | None
    category: str | None
    minimum_price: Decimal | None
    maximum_price: Decimal | None
    closing_after: datetime | None
    closing_before: datetime | None
    view: ListingView
    sort: ListingSort | None
    page: int
    page_size: int


class AuctionReadRepository:
    """Execute public read queries without exposing persistence internals."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ping(self) -> None:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def list_listings(
        self,
        filters: ListingFilters,
        *,
        request_time: datetime,
    ) -> ListingPage:
        statement = self._current_listing_statement(request_time).where(
            *self._listing_conditions(filters, request_time)
        )
        sort = filters.sort or _default_listing_sort(filters.view)
        with self._engine.connect() as connection:
            total = int(
                connection.scalar(select(func.count()).select_from(statement.subquery())) or 0
            )
            rows = connection.execute(
                statement.order_by(*self._listing_order(sort))
                .limit(filters.page_size)
                .offset((filters.page - 1) * filters.page_size)
            ).mappings()
            listings = tuple(_listing_summary_from_row(row) for row in rows)
        return ListingPage(
            items=listings,
            page_info=_page_info(total, filters.page, filters.page_size),
        )

    def get_listing(self, source_id: str, *, request_time: datetime) -> ListingDetail | None:
        statement = self._current_listing_statement(request_time).where(
            auction_items.c.source_id == source_id
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return _listing_detail_from_row(row) if row is not None else None

    def list_locations(
        self,
        *,
        view: ListingView,
        request_time: datetime,
        limit: int,
    ) -> FacetList:
        listings = self._view_listing_statement(view, request_time).subquery()
        location = func.coalesce(
            listings.c.location_canonical,
            listings.c.location_raw,
        ).label("value")
        statement = (
            select(location, func.count(listings.c.source_id).label("count"))
            .where(location.is_not(None), location != "")
            .group_by(location)
            .order_by(func.lower(location), location)
            .limit(limit)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings()
            facets = tuple(_facet_from_row(row) for row in rows)
        return FacetList(items=facets)

    def list_categories(
        self,
        *,
        view: ListingView,
        request_time: datetime,
        limit: int,
    ) -> FacetList:
        listings = self._view_listing_statement(view, request_time).subquery()
        category = func.coalesce(
            listings.c.category_canonical,
            listings.c.category_raw,
        ).label("value")
        statement = (
            select(category, func.count(listings.c.source_id).label("count"))
            .where(category.is_not(None), category != "")
            .group_by(category)
            .order_by(func.lower(category), category)
            .limit(limit)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings()
            facets = tuple(_facet_from_row(row) for row in rows)
        return FacetList(items=facets)

    def scrape_status(self, *, request_time: datetime) -> ScrapeStatus:
        run_columns = (
            scrape_runs.c.started_at,
            scrape_runs.c.finished_at,
            scrape_runs.c.status,
            scrape_runs.c.mode,
            scrape_runs.c.requested_limit,
            scrape_runs.c.pages_visited,
            scrape_runs.c.items_seen,
            scrape_runs.c.items_created,
            scrape_runs.c.items_updated,
            scrape_runs.c.observations_created,
            scrape_runs.c.item_failures,
            scrape_runs.c.source_requests,
            scrape_runs.c.source_responses,
            scrape_runs.c.source_retries,
            scrape_runs.c.rate_limit_responses,
            scrape_runs.c.source_transport_errors,
            scrape_runs.c.source_request_duration_ms,
            scrape_runs.c.source_request_wait_duration_ms,
            scrape_runs.c.source_retry_wait_duration_ms,
            scrape_runs.c.completion_status,
            scrape_runs.c.expected_product_groups,
            scrape_runs.c.processed_product_groups,
            scrape_runs.c.unique_listings_enumerated,
            scrape_runs.c.duplicate_listings_enumerated,
            scrape_runs.c.detail_attempted,
            scrape_runs.c.detail_succeeded,
            scrape_runs.c.persistence_succeeded,
            scrape_runs.c.persistence_failures,
            scrape_runs.c.enumeration_complete,
        )
        latest_run_statement = select(*run_columns).order_by(
            scrape_runs.c.started_at.desc(),
            scrape_runs.c.created_at.desc(),
            scrape_runs.c.id.desc(),
        )
        latest_successful_statement = latest_run_statement.where(
            scrape_runs.c.status == "succeeded"
        )
        latest_complete_statement = latest_run_statement.where(
            scrape_runs.c.status == "succeeded",
            scrape_runs.c.completion_status == "complete",
        )
        with self._engine.connect() as connection:
            latest_run = connection.execute(latest_run_statement.limit(1)).mappings().one_or_none()
            latest_successful_run = (
                connection.execute(latest_successful_statement.limit(1)).mappings().one_or_none()
            )
            latest_complete_run = (
                connection.execute(latest_complete_statement.limit(1)).mappings().one_or_none()
            )
            listing_count, latest_listing_seen_at, active_listing_count, stale_listing_count = (
                connection.execute(
                    select(
                        func.count(auction_items.c.id),
                        func.max(auction_items.c.last_seen_at),
                        func.count()
                        .filter(auction_items.c.inventory_state == "current"),
                        func.count().filter(auction_items.c.inventory_state == "stale"),
                    )
                ).one()
            )
        latest_complete_summary = (
            _scrape_run_from_row(latest_complete_run)
            if latest_complete_run is not None
            else None
        )
        latest_complete_age_seconds = None
        if latest_complete_summary is not None and latest_complete_summary.finished_at is not None:
            latest_complete_age_seconds = max(
                0,
                int((request_time - latest_complete_summary.finished_at).total_seconds()),
            )
        return ScrapeStatus(
            latest_run=_scrape_run_from_row(latest_run) if latest_run is not None else None,
            latest_successful_run=(
                _scrape_run_from_row(latest_successful_run)
                if latest_successful_run is not None
                else None
            ),
            listing_count=int(listing_count),
            latest_listing_seen_at=latest_listing_seen_at,
            latest_complete_run=latest_complete_summary,
            latest_complete_age_seconds=latest_complete_age_seconds,
            active_listing_count=int(active_listing_count),
            stale_listing_count=int(stale_listing_count),
        )

    @staticmethod
    def _current_listing_statement(request_time: datetime) -> Select[tuple[Any, ...]]:
        candidates = (
            select(
                auction_items.c.id.label("auction_item_id"),
                item_observations.c.id.label("observation_id"),
                func.row_number()
                .over(
                    partition_by=auction_items.c.id,
                    order_by=(
                        (item_observations.c.observed_at == auction_items.c.last_seen_at).desc(),
                        (item_observations.c.observed_at <= auction_items.c.last_seen_at).desc(),
                        item_observations.c.observed_at.desc(),
                        scrape_runs.c.started_at.desc(),
                        scrape_runs.c.created_at.desc(),
                        item_observations.c.created_at.desc(),
                        item_observations.c.id.desc(),
                    ),
                )
                .label("selection_rank"),
            )
            .select_from(
                auction_items.join(
                    item_observations,
                    and_(
                        item_observations.c.auction_item_id == auction_items.c.id,
                        item_observations.c.observation_hash
                        == auction_items.c.current_observation_hash,
                    ),
                ).join(scrape_runs, scrape_runs.c.id == item_observations.c.scrape_run_id)
            )
            .cte("current_observation_candidates")
        )
        return select(
            auction_items.c.source_id,
            auction_items.c.canonical_source_url,
            auction_items.c.title,
            auction_items.c.description,
            auction_items.c.category_raw,
            auction_items.c.category_canonical,
            auction_items.c.location_raw,
            auction_items.c.location_canonical,
            auction_items.c.location_qualifier,
            auction_items.c.location_normalization_status,
            auction_items.c.pickup_details,
            auction_items.c.image_urls,
            auction_items.c.status,
            auction_items.c.status_raw,
            auction_items.c.first_seen_at,
            auction_items.c.last_seen_at,
            auction_items.c.last_changed_at,
            auction_items.c.closed_at,
            auction_items.c.last_complete_seen_at,
            auction_items.c.complete_absence_count,
            auction_items.c.inventory_state,
            item_observations.c.current_bid,
            item_observations.c.minimum_bid,
            item_observations.c.starting_bid,
            item_observations.c.bid_count,
            item_observations.c.closing_at,
            item_observations.c.observed_at,
            AuctionReadRepository._availability_expression(request_time).label("availability"),
        ).select_from(
            auction_items.join(
                candidates,
                and_(
                    candidates.c.auction_item_id == auction_items.c.id,
                    candidates.c.selection_rank == 1,
                ),
            ).join(item_observations, item_observations.c.id == candidates.c.observation_id)
        )

    @staticmethod
    def _listing_conditions(
        filters: ListingFilters,
        request_time: datetime,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        view_condition = AuctionReadRepository._view_condition(filters.view, request_time)
        if view_condition is not None:
            conditions.append(view_condition)
        keyword = _normalized_text(filters.keyword)
        if keyword is not None:
            pattern = _like_pattern(keyword)
            conditions.append(
                or_(
                    auction_items.c.title.ilike(pattern, escape="\\"),
                    auction_items.c.description.ilike(pattern, escape="\\"),
                )
            )
        location = _normalized_text(filters.location)
        if location is not None:
            conditions.append(
                or_(
                    func.lower(auction_items.c.location_canonical) == location,
                    and_(
                        auction_items.c.location_canonical.is_(None),
                        func.lower(auction_items.c.location_raw) == location,
                    ),
                )
            )
        category = _normalized_text(filters.category)
        if category is not None:
            conditions.append(
                func.lower(
                    func.coalesce(
                        auction_items.c.category_canonical,
                        auction_items.c.category_raw,
                    )
                )
                == category
            )
        if filters.minimum_price is not None:
            conditions.append(item_observations.c.current_bid >= filters.minimum_price)
        if filters.maximum_price is not None:
            conditions.append(item_observations.c.current_bid <= filters.maximum_price)
        if filters.closing_after is not None:
            conditions.append(item_observations.c.closing_at >= filters.closing_after)
        if filters.closing_before is not None:
            conditions.append(item_observations.c.closing_at <= filters.closing_before)
        return conditions

    @staticmethod
    def _view_listing_statement(
        view: ListingView,
        request_time: datetime,
    ) -> Select[tuple[Any, ...]]:
        statement = AuctionReadRepository._current_listing_statement(request_time)
        view_condition = AuctionReadRepository._view_condition(view, request_time)
        return statement.where(view_condition) if view_condition is not None else statement

    @staticmethod
    def _view_condition(
        view: ListingView,
        request_time: datetime,
    ) -> ColumnElement[bool] | None:
        is_open = auction_items.c.status == AuctionStatus.OPEN.value
        closing_at = item_observations.c.closing_at
        if view is ListingView.ACTIVE:
            return and_(
                auction_items.c.inventory_state == "current",
                is_open,
                or_(closing_at.is_(None), closing_at > request_time),
            )
        if view is ListingView.ENDED:
            return or_(
                auction_items.c.status.in_(
                    (AuctionStatus.CLOSED.value, AuctionStatus.WITHDRAWN.value)
                ),
                and_(
                    is_open,
                    closing_at.is_not(None),
                    closing_at <= request_time,
                ),
            )
        if view is ListingView.ALL:
            return None
        raise AssertionError(f"unsupported listing view: {view}")

    @staticmethod
    def _availability_expression(request_time: datetime) -> ColumnElement[str]:
        is_open = auction_items.c.status == AuctionStatus.OPEN.value
        closing_at = item_observations.c.closing_at
        return case(
            (
                auction_items.c.status == AuctionStatus.CLOSED.value,
                ListingAvailability.CLOSED.value,
            ),
            (
                auction_items.c.status == AuctionStatus.WITHDRAWN.value,
                ListingAvailability.WITHDRAWN.value,
            ),
            (
                and_(
                    is_open,
                    closing_at.is_not(None),
                    closing_at <= request_time,
                ),
                ListingAvailability.SCHEDULED_CLOSING_PASSED.value,
            ),
            (
                and_(is_open, closing_at > request_time),
                ListingAvailability.ACTIVE.value,
            ),
            else_=ListingAvailability.UNKNOWN.value,
        )

    @staticmethod
    def _listing_order(sort: ListingSort) -> tuple[ColumnElement[Any], ...]:
        tie_breaker = auction_items.c.source_id.asc()
        if sort is ListingSort.CLOSING_SOON:
            return (item_observations.c.closing_at.asc().nulls_last(), tie_breaker)
        if sort is ListingSort.CLOSING_LATEST:
            return (item_observations.c.closing_at.desc().nulls_last(), tie_breaker)
        if sort is ListingSort.PRICE_LOW:
            return (item_observations.c.current_bid.asc().nulls_last(), tie_breaker)
        if sort is ListingSort.PRICE_HIGH:
            return (item_observations.c.current_bid.desc().nulls_last(), tie_breaker)
        if sort is ListingSort.NEWEST_SEEN:
            return (auction_items.c.last_seen_at.desc(), tie_breaker)
        if sort is ListingSort.MOST_BIDS:
            return (item_observations.c.bid_count.desc().nulls_last(), tie_breaker)
        raise AssertionError(f"unsupported listing sort: {sort}")


def _listing_summary_from_row(row: RowMapping) -> ListingSummary:
    return ListingSummary.model_validate(_listing_values(row))


def _listing_detail_from_row(row: RowMapping) -> ListingDetail:
    values = _listing_values(row)
    values.update(
        {
            "description": row["description"],
            "category_raw": row["category_raw"],
            "category_canonical": row["category_canonical"],
            "location_raw": row["location_raw"],
            "location_canonical": row["location_canonical"],
            "location_normalization_status": row["location_normalization_status"],
            "pickup_details": row["pickup_details"],
            "status_raw": row["status_raw"],
        }
    )
    return ListingDetail.model_validate(values)


def _listing_values(row: RowMapping) -> dict[str, object]:
    image_urls = tuple(cast(list[str], row["image_urls"]))
    category = row["category_canonical"] or row["category_raw"]
    location = row["location_canonical"] or row["location_raw"]
    return {
        "source_id": row["source_id"],
        "canonical_source_url": row["canonical_source_url"],
        "title": row["title"],
        "category": category,
        "location": location,
        "location_qualifier": row["location_qualifier"],
        "image_urls": image_urls,
        "current_bid": row["current_bid"],
        "minimum_bid": row["minimum_bid"],
        "starting_bid": row["starting_bid"],
        "bid_count": row["bid_count"],
        "closing_at": row["closing_at"],
        "status": row["status"],
        "availability": row["availability"],
        "observed_at": row["observed_at"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "last_changed_at": row["last_changed_at"],
        "closed_at": row["closed_at"],
        "last_complete_seen_at": row["last_complete_seen_at"],
        "complete_absence_count": row["complete_absence_count"],
        "inventory_state": row["inventory_state"],
    }


def _facet_from_row(row: RowMapping) -> Facet:
    return Facet.model_validate({"value": row["value"], "count": int(row["count"])})


def _scrape_run_from_row(row: RowMapping) -> ScrapeRunSummary:
    return ScrapeRunSummary.model_validate(
        {
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "status": row["status"],
            "mode": row["mode"],
            "requested_limit": row["requested_limit"],
            "pages_visited": row["pages_visited"],
            "items_seen": row["items_seen"],
            "items_created": row["items_created"],
            "items_updated": row["items_updated"],
            "observations_created": row["observations_created"],
            "item_failures": row["item_failures"],
            "source_requests": row["source_requests"],
            "source_responses": row["source_responses"],
            "source_retries": row["source_retries"],
            "rate_limit_responses": row["rate_limit_responses"],
            "source_transport_errors": row["source_transport_errors"],
            "source_request_duration_ms": row["source_request_duration_ms"],
            "source_request_wait_duration_ms": row["source_request_wait_duration_ms"],
            "source_retry_wait_duration_ms": row["source_retry_wait_duration_ms"],
            "completion_status": row["completion_status"],
            "expected_product_groups": row["expected_product_groups"],
            "processed_product_groups": row["processed_product_groups"],
            "unique_listings_enumerated": row["unique_listings_enumerated"],
            "duplicate_listings_enumerated": row["duplicate_listings_enumerated"],
            "detail_attempted": row["detail_attempted"],
            "detail_succeeded": row["detail_succeeded"],
            "persistence_succeeded": row["persistence_succeeded"],
            "persistence_failures": row["persistence_failures"],
            "enumeration_complete": bool(row["enumeration_complete"]),
        }
    )


def _page_info(total_items: int, page: int, page_size: int) -> PageInfo:
    total_pages = (total_items + page_size - 1) // page_size if total_items else 0
    return PageInfo(
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
    )


def _default_listing_sort(view: ListingView) -> ListingSort:
    if view is ListingView.ENDED:
        return ListingSort.CLOSING_LATEST
    if view in {ListingView.ACTIVE, ListingView.ALL}:
        return ListingSort.CLOSING_SOON
    raise AssertionError(f"unsupported listing view: {view}")


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split()).casefold()
    return normalized or None


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
