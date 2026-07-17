import createClient from "openapi-fetch";

import type { components, operations, paths } from "./types";

export type ListingSummary = components["schemas"]["ListingSummary"];
export type ListingDetail = components["schemas"]["ListingDetail"];
export type ListingPage = components["schemas"]["ListingPage"];
export type FacetList = components["schemas"]["FacetList"];
export type ScrapeStatus = components["schemas"]["ScrapeStatus"];
export type AuctionStatus = components["schemas"]["AuctionStatus"];
export type ListingSort = components["schemas"]["ListingSort"];
export type ListingQuery = NonNullable<
  operations["list_listings_api_listings_get"]["parameters"]["query"]
>;

const client = createClient<paths>({
  baseUrl: typeof window === "undefined" ? "http://localhost" : window.location.origin,
  fetch: (...arguments_) => globalThis.fetch(...arguments_),
});

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

type ApiResult<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

async function unwrap<T>(request: Promise<ApiResult<T>>): Promise<T> {
  try {
    const { data, error, response } = await request;
    if (response.ok && data !== undefined) {
      return data;
    }

    const detail = error as { error?: { code?: unknown; message?: unknown } } | undefined;
    const message =
      typeof detail?.error?.message === "string"
        ? detail.error.message
        : response.ok
          ? "The response could not be read."
          : "The request could not be completed.";
    const code = typeof detail?.error?.code === "string" ? detail.error.code : null;
    throw new ApiRequestError(message, response.status, code);
  } catch (error) {
    if (error instanceof ApiRequestError || error instanceof DOMException) {
      throw error;
    }
    throw new ApiRequestError("The service could not be reached.", 0);
  }
}

export function getListings(query: ListingQuery, signal?: AbortSignal): Promise<ListingPage> {
  return unwrap(client.GET("/api/listings", { params: { query }, signal }));
}

export function getListing(sourceId: string, signal?: AbortSignal): Promise<ListingDetail> {
  return unwrap(
    client.GET("/api/listings/{source_id}", {
      params: { path: { source_id: sourceId } },
      signal,
    }),
  );
}

export function getLocations(signal?: AbortSignal): Promise<FacetList> {
  return unwrap(client.GET("/api/locations", { params: { query: { limit: 500 } }, signal }));
}

export function getCategories(signal?: AbortSignal): Promise<FacetList> {
  return unwrap(client.GET("/api/categories", { params: { query: { limit: 500 } }, signal }));
}

export function getScrapeStatus(signal?: AbortSignal): Promise<ScrapeStatus> {
  return unwrap(client.GET("/api/scrape-status", { signal }));
}
