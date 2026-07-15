from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class AuctionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    WITHDRAWN = "withdrawn"
    UNKNOWN = "unknown"


class LocationStatus(StrEnum):
    EXACT = "exact"
    ALIAS = "alias"
    UNKNOWN = "unknown"


class NormalizedLocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw: str
    canonical: str
    qualifier: str | None = None
    status: LocationStatus


class SearchResultRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_url: HttpUrl | None = None
    source_id: str | None = None
    location_raw: str | None = None
    summary_cells: tuple[str, ...] = ()
    detail_text: str = ""


class AuctionItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str | None = None
    source_url: HttpUrl
    source_search_url: HttpUrl | None = None
    title: str
    description: str | None = None
    category_raw: str | None = None
    category_canonical: str | None = None
    location_raw: str | None = None
    location_canonical: str | None = None
    location_qualifier: str | None = None
    current_bid: Decimal | None = Field(default=None, ge=0)
    minimum_bid: Decimal | None = Field(default=None, ge=0)
    starting_bid: Decimal | None = Field(default=None, ge=0)
    bid_count: int | None = Field(default=None, ge=0)
    closing_at: datetime | None = None
    status_raw: str | None = None
    status: AuctionStatus = AuctionStatus.UNKNOWN
    image_urls: tuple[HttpUrl, ...] = ()
    first_seen_at: datetime
    last_seen_at: datetime
    last_changed_at: datetime
    scraped_at: datetime
    raw_content_hash: str = Field(min_length=64, max_length=64)
    parser_version: str

    @field_validator(
        "first_seen_at",
        "last_seen_at",
        "last_changed_at",
        "scraped_at",
        "closing_at",
    )
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("datetime must include a timezone")
        return value
