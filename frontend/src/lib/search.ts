import type { AuctionStatus, ListingQuery, ListingSort } from "../api/client";
import { dateInputToUtc } from "./time";

const statuses: readonly AuctionStatus[] = ["open", "closed", "withdrawn", "unknown"];
const sorts: readonly ListingSort[] = [
  "closing_soon",
  "closing_latest",
  "price_low",
  "price_high",
  "newest_seen",
  "most_bids",
];

export const defaultListingSearch = {
  category: "",
  closingAfter: "",
  closingBefore: "",
  keyword: "",
  location: "",
  maxPrice: "",
  minPrice: "",
  page: 1,
  sort: "closing_soon" as ListingSort,
  status: "open" as AuctionStatus,
};

export type ListingSearch = typeof defaultListingSearch;

const decimalPattern = /^\d+(?:\.\d{1,2})?$/;
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
const maximumFilterLength = 200;

function stringValue(parameters: URLSearchParams, key: string): string {
  return parameters.get(key)?.trim() ?? "";
}

function validFilter(value: string): string {
  return value.length <= maximumFilterLength ? value : "";
}

function validStatus(value: string): AuctionStatus {
  return statuses.includes(value as AuctionStatus)
    ? (value as AuctionStatus)
    : defaultListingSearch.status;
}

function validSort(value: string): ListingSort {
  return sorts.includes(value as ListingSort) ? (value as ListingSort) : defaultListingSearch.sort;
}

function validPage(value: string): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 1 && parsed <= 10_000 ? parsed : 1;
}

function validDecimal(value: string): string {
  return decimalPattern.test(value) ? value : "";
}

function validDate(value: string): string {
  if (!datePattern.test(value)) {
    return "";
  }
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day
    ? value
    : "";
}

export function parseListingSearch(parameters: URLSearchParams): ListingSearch {
  return {
    category: validFilter(stringValue(parameters, "category")),
    closingAfter: validDate(stringValue(parameters, "closing_after")),
    closingBefore: validDate(stringValue(parameters, "closing_before")),
    keyword: validFilter(stringValue(parameters, "keyword")),
    location: validFilter(stringValue(parameters, "location")),
    maxPrice: validDecimal(stringValue(parameters, "max_price")),
    minPrice: validDecimal(stringValue(parameters, "min_price")),
    page: validPage(stringValue(parameters, "page")),
    sort: validSort(stringValue(parameters, "sort")),
    status: validStatus(stringValue(parameters, "status")),
  };
}

export function listingSearchParams(search: ListingSearch): URLSearchParams {
  const parameters = new URLSearchParams();
  const add = (key: string, value: string): void => {
    if (value) {
      parameters.set(key, value);
    }
  };

  add("keyword", search.keyword.trim());
  add("location", search.location.trim());
  add("category", search.category.trim());
  if (search.status !== defaultListingSearch.status) {
    parameters.set("status", search.status);
  }
  add("min_price", search.minPrice);
  add("max_price", search.maxPrice);
  add("closing_after", search.closingAfter);
  add("closing_before", search.closingBefore);
  if (search.sort !== defaultListingSearch.sort) {
    parameters.set("sort", search.sort);
  }
  if (search.page > 1) {
    parameters.set("page", String(search.page));
  }
  return parameters;
}

export function listingQuery(search: ListingSearch): ListingQuery {
  return {
    category: search.category || undefined,
    closing_after: dateInputToUtc(search.closingAfter, "start"),
    closing_before: dateInputToUtc(search.closingBefore, "end"),
    keyword: search.keyword || undefined,
    location: search.location || undefined,
    max_price: search.maxPrice || undefined,
    min_price: search.minPrice || undefined,
    page: search.page,
    page_size: 25,
    sort: search.sort,
    status: search.status,
  };
}

export function withFirstPage(search: ListingSearch): ListingSearch {
  return { ...search, page: 1 };
}

export const sortLabels: Record<ListingSort, string> = {
  closing_soon: "Closing soon",
  closing_latest: "Closing latest",
  price_low: "Price low to high",
  price_high: "Price high to low",
  newest_seen: "Newest seen",
  most_bids: "Most bids",
};
