"""FastAPI application for public, read-only auction data."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from bc_auction.api_models import (
    ErrorResponse,
    FacetList,
    ListingDetail,
    ListingPage,
    ListingSort,
    ListingView,
    ScrapeStatus,
)
from bc_auction.database import DatabaseConfigurationError, create_postgres_engine
from bc_auction.read_repository import AuctionReadRepository, ListingFilters

_DEFAULT_PAGE_SIZE = 25
_MAX_PAGE_SIZE = 100
_DEFAULT_FACET_LIMIT = 100
_MAX_FACET_LIMIT = 500
_MAX_PAGE = 10_000
_MAX_BID_VALUE = Decimal("999999999999.99")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def create_app(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    now_provider: Callable[[], datetime] = _utc_now,
) -> FastAPI:
    """Create the API application without granting any write capability."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns_engine = engine is None
        resolved_engine = engine
        try:
            if resolved_engine is None:
                resolved_engine = create_postgres_engine(
                    _resolve_database_url(database_url)
                )
            repository = AuctionReadRepository(resolved_engine)
            repository.ping()
            app.state.read_repository = repository
            yield
        except (DatabaseConfigurationError, SQLAlchemyError) as exc:
            raise RuntimeError("database is unavailable") from exc
        finally:
            if owns_engine and resolved_engine is not None:
                resolved_engine.dispose()

    app = FastAPI(
        title="BC Auction Explorer API",
        version="0.1.0",
        description="Read-only public data from the BC Auction Explorer index.",
        lifespan=lifespan,
    )
    app.add_exception_handler(RequestValidationError, _request_validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_exception)
    app.add_exception_handler(SQLAlchemyError, _database_error)
    app.add_exception_handler(Exception, _unexpected_error)

    @app.get(
        "/api/listings",
        response_model=ListingPage,
        responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    )
    def list_listings(
        repository: Annotated[AuctionReadRepository, Depends(_read_repository)],
        keyword: Annotated[str | None, Query(max_length=200)] = None,
        location: Annotated[str | None, Query(max_length=200)] = None,
        category: Annotated[str | None, Query(max_length=200)] = None,
        min_price: Annotated[Decimal | None, Query(ge=0, le=_MAX_BID_VALUE)] = None,
        max_price: Annotated[Decimal | None, Query(ge=0, le=_MAX_BID_VALUE)] = None,
        closing_after: datetime | None = None,
        closing_before: datetime | None = None,
        view: ListingView = ListingView.ACTIVE,
        sort: ListingSort | None = None,
        page: Annotated[int, Query(ge=1, le=_MAX_PAGE)] = 1,
        page_size: Annotated[int, Query(ge=1, le=_MAX_PAGE_SIZE)] = _DEFAULT_PAGE_SIZE,
    ) -> ListingPage:
        if min_price is not None and max_price is not None and min_price > max_price:
            _raise_invalid_filter("min_price cannot be greater than max_price")
        normalized_closing_after = _utc_query_datetime(closing_after, "closing_after")
        normalized_closing_before = _utc_query_datetime(closing_before, "closing_before")
        if (
            normalized_closing_after is not None
            and normalized_closing_before is not None
            and normalized_closing_after > normalized_closing_before
        ):
            _raise_invalid_filter("closing_after cannot be later than closing_before")
        request_time = _provided_utc_now(now_provider)
        return repository.list_listings(
            ListingFilters(
                keyword=keyword,
                location=location,
                category=category,
                minimum_price=min_price,
                maximum_price=max_price,
                closing_after=normalized_closing_after,
                closing_before=normalized_closing_before,
                view=view,
                sort=sort,
                page=page,
                page_size=page_size,
            ),
            request_time=request_time,
        )

    @app.get(
        "/api/listings/{source_id}",
        response_model=ListingDetail,
        responses={
            404: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def get_listing(
        source_id: Annotated[str, Path(min_length=1, max_length=64)],
        repository: Annotated[AuctionReadRepository, Depends(_read_repository)],
    ) -> ListingDetail:
        listing = repository.get_listing(
            source_id,
            request_time=_provided_utc_now(now_provider),
        )
        if listing is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "listing_not_found",
                    "message": "Listing was not found",
                },
            )
        return listing

    @app.get(
        "/api/locations",
        response_model=FacetList,
        responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    )
    def list_locations(
        repository: Annotated[AuctionReadRepository, Depends(_read_repository)],
        view: ListingView = ListingView.ACTIVE,
        limit: Annotated[int, Query(ge=1, le=_MAX_FACET_LIMIT)] = _DEFAULT_FACET_LIMIT,
    ) -> FacetList:
        return repository.list_locations(
            view=view,
            request_time=_provided_utc_now(now_provider),
            limit=limit,
        )

    @app.get(
        "/api/categories",
        response_model=FacetList,
        responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    )
    def list_categories(
        repository: Annotated[AuctionReadRepository, Depends(_read_repository)],
        view: ListingView = ListingView.ACTIVE,
        limit: Annotated[int, Query(ge=1, le=_MAX_FACET_LIMIT)] = _DEFAULT_FACET_LIMIT,
    ) -> FacetList:
        return repository.list_categories(
            view=view,
            request_time=_provided_utc_now(now_provider),
            limit=limit,
        )

    @app.get(
        "/api/scrape-status",
        response_model=ScrapeStatus,
        responses={503: {"model": ErrorResponse}},
    )
    def scrape_status(
        repository: Annotated[AuctionReadRepository, Depends(_read_repository)],
    ) -> ScrapeStatus:
        return repository.scrape_status(request_time=_provided_utc_now(now_provider))

    return app


def _resolve_database_url(database_url: str | None) -> str:
    resolved_url = database_url or os.environ.get("BC_AUCTION_DATABASE_URL")
    if not resolved_url:
        raise DatabaseConfigurationError("BC_AUCTION_DATABASE_URL is required")
    return resolved_url


def _read_repository(request: Request) -> AuctionReadRepository:
    repository = getattr(request.app.state, "read_repository", None)
    if not isinstance(repository, AuctionReadRepository):
        raise RuntimeError("read repository is not available")
    return repository


def _provided_utc_now(now_provider: Callable[[], datetime]) -> datetime:
    value = now_provider()
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("now_provider must return a timezone-aware datetime")
    return value.astimezone(UTC)


def _utc_query_datetime(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        _raise_invalid_filter(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _raise_invalid_filter(message: str) -> None:
    raise HTTPException(
        status_code=422,
        detail={"code": "invalid_filter", "message": message},
    )


async def _request_validation_error(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        return _unexpected_error_response()
    return _error_response(
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        details=[
            {
                "location": list(error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ],
    )


async def _http_exception(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        return _unexpected_error_response()
    if isinstance(exc.detail, dict):
        code = str(exc.detail.get("code", "request_error"))
        message = str(exc.detail.get("message", "Request could not be completed"))
        details = exc.detail.get("details")
    else:
        code = "request_error"
        message = "Request could not be completed"
        details = None
    return _error_response(
        status_code=exc.status_code,
        code=code,
        message=message,
        details=details,
    )


async def _database_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, SQLAlchemyError):
        return _unexpected_error_response()
    return _error_response(
        status_code=503,
        code="database_unavailable",
        message="Database is temporarily unavailable",
    )


async def _unexpected_error(_: Request, __: Exception) -> JSONResponse:
    return _unexpected_error_response()


def _unexpected_error_response() -> JSONResponse:
    return _error_response(
        status_code=500,
        code="internal_error",
        message="An unexpected error occurred",
    )


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: object | None = None,
) -> JSONResponse:
    response = ErrorResponse.model_validate(
        {"error": {"code": code, "message": message, "details": details}}
    )
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))


app = create_app()
