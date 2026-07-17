import { useEffect, useState, type FormEvent } from "react";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";

import { ApiRequestError, getCategories, getListings, getLocations, type ListingSummary } from "../api/client";
import { ListingImage } from "../components/ListingImage";
import { StatusBadge } from "../components/StatusBadge";
import { bidCount, currency } from "../lib/format";
import {
  defaultListingSearch,
  listingQuery,
  listingSearchParams,
  parseListingSearch,
  sortLabels,
  withFirstPage,
  type ListingSearch,
} from "../lib/search";
import { pacificDateTime } from "../lib/time";

const statusLabels = {
  open: "Open",
  closed: "Closed",
  withdrawn: "Withdrawn",
  unknown: "Unknown",
} as const;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function isPastClosing(listing: ListingSummary): boolean {
  return (
    listing.status === "open" &&
    listing.closing_at !== null &&
    listing.closing_at !== undefined &&
    new Date(listing.closing_at).getTime() < Date.now()
  );
}

function listingPath(sourceId: string, search: string): string {
  const from = search ? `?from=${encodeURIComponent(search)}` : "";
  return `/listings/${encodeURIComponent(sourceId)}${from}`;
}

export function ListingBrowserPage() {
  const [searchParameters, setSearchParameters] = useSearchParams();
  const search = parseListingSearch(searchParameters);
  const [draft, setDraft] = useState<ListingSearch>(search);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    document.title = "Browse listings | BC Auction Explorer";
    setDraft(search);
  }, [searchParameters]);

  const listings = useQuery({
    queryKey: ["listings", search],
    queryFn: ({ signal }) => getListings(listingQuery(search), signal),
    placeholderData: keepPreviousData,
  });
  const locations = useQuery({
    queryKey: ["locations"],
    queryFn: ({ signal }) => getLocations(signal),
    staleTime: 300_000,
  });
  const categories = useQuery({
    queryKey: ["categories"],
    queryFn: ({ signal }) => getCategories(signal),
    staleTime: 300_000,
  });

  const updateSearch = (next: ListingSearch): void => {
    setSearchParameters(listingSearchParams(next));
  };

  useEffect(() => {
    const canonicalParameters = listingSearchParams(search);
    if (searchParameters.toString() !== canonicalParameters.toString()) {
      setSearchParameters(canonicalParameters, { replace: true });
    }
  }, [search, searchParameters, setSearchParameters]);

  useEffect(() => {
    if (listings.isPlaceholderData || !listings.data) {
      return;
    }
    const lastPage = Math.max(1, listings.data.page_info.total_pages);
    if (search.page > lastPage) {
      setSearchParameters(listingSearchParams({ ...search, page: lastPage }), { replace: true });
    }
  }, [listings.data, listings.isPlaceholderData, search, setSearchParameters]);

  const applyFilters = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const minimum = draft.minPrice ? Number(draft.minPrice) : undefined;
    const maximum = draft.maxPrice ? Number(draft.maxPrice) : undefined;
    if (minimum !== undefined && maximum !== undefined && minimum > maximum) {
      setFormError("Minimum current bid cannot be greater than maximum current bid.");
      return;
    }
    if (draft.closingAfter && draft.closingBefore && draft.closingAfter > draft.closingBefore) {
      setFormError("Closing after cannot be later than closing before.");
      return;
    }
    setFormError(null);
    updateSearch(withFirstPage(draft));
  };

  const clearFilters = (): void => {
    setFormError(null);
    setDraft(defaultListingSearch);
    updateSearch(defaultListingSearch);
  };

  const updateDraft = <Key extends keyof ListingSearch>(key: Key, value: ListingSearch[Key]): void => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const pageInfo = listings.data?.page_info;
  const resultCount = pageInfo?.total_items ?? 0;

  return (
    <section className="listing-browser" aria-labelledby="browse-title">
      <div className="intro">
        <p className="eyebrow">Public auction listings</p>
        <h1 id="browse-title">Browse current auction listings</h1>
        <p>
          Search title and description text, then confirm details on the original auction listing.
        </p>
      </div>

      <div className="browse-layout">
        <div className="filter-rail">
          <details className="filter-panel" open>
            <summary>Filters</summary>
            <form className="filter-form" onSubmit={applyFilters}>
              <label>
                Keyword
                <input
                  onChange={(event) => updateDraft("keyword", event.target.value)}
                  placeholder="Search title and description"
                  type="search"
                  value={draft.keyword}
                />
              </label>
              <label>
                Location
                <select
                  onChange={(event) => updateDraft("location", event.target.value)}
                  value={draft.location}
                >
                  <option value="">All locations</option>
                  {locations.data?.items.map((facet) => (
                    <option key={facet.value} value={facet.value}>
                      {facet.value} ({facet.count})
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Category
                <select
                  onChange={(event) => updateDraft("category", event.target.value)}
                  value={draft.category}
                >
                  <option value="">All categories</option>
                  {categories.data?.items.map((facet) => (
                    <option key={facet.value} value={facet.value}>
                      {facet.value} ({facet.count})
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Status
                <select
                  onChange={(event) => updateDraft("status", event.target.value as ListingSearch["status"])}
                  value={draft.status}
                >
                  {Object.entries(statusLabels).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <fieldset>
                <legend>Current bid range</legend>
                <label>
                  Minimum
                  <input
                    inputMode="decimal"
                    min="0"
                    onChange={(event) => updateDraft("minPrice", event.target.value)}
                    placeholder="0.00"
                    step="0.01"
                    type="number"
                    value={draft.minPrice}
                  />
                </label>
                <label>
                  Maximum
                  <input
                    inputMode="decimal"
                    min="0"
                    onChange={(event) => updateDraft("maxPrice", event.target.value)}
                    placeholder="No maximum"
                    step="0.01"
                    type="number"
                    value={draft.maxPrice}
                  />
                </label>
              </fieldset>
              <fieldset>
                <legend>Closing date in Pacific time</legend>
                <label>
                  On or after
                  <input
                    onChange={(event) => updateDraft("closingAfter", event.target.value)}
                    type="date"
                    value={draft.closingAfter}
                  />
                </label>
                <label>
                  On or before
                  <input
                    onChange={(event) => updateDraft("closingBefore", event.target.value)}
                    type="date"
                    value={draft.closingBefore}
                  />
                </label>
              </fieldset>
              {formError ? <p className="form-error" role="alert">{formError}</p> : null}
              {(locations.isError || categories.isError) && (
                <p className="form-note">Some filter options are temporarily unavailable.</p>
              )}
              <div className="button-row">
                <button type="submit">Apply filters</button>
                <button className="button-link" onClick={clearFilters} type="button">
                  Clear
                </button>
              </div>
              <p className="facet-note">Location and category counts cover all indexed listings.</p>
            </form>
          </details>
        </div>

        <div className="results-column">
          <div className="results-toolbar">
            <p aria-live="polite" className="result-count" role="status">
              {listings.isLoading
                ? "Loading listings"
                : `${resultCount} ${resultCount === 1 ? "listing" : "listings"}`}
            </p>
            <label className="sort-control">
              Sort by
              <select
                onChange={(event) =>
                  updateSearch(
                    withFirstPage({ ...search, sort: event.target.value as ListingSearch["sort"] }),
                  )
                }
                value={search.sort}
              >
                {Object.entries(sortLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {listings.isError ? (
            <div className="error-panel" role="alert">
              <h2>Listings are unavailable</h2>
              <p>{errorMessage(listings.error)}</p>
              <button onClick={() => void listings.refetch()} type="button">
                Try again
              </button>
            </div>
          ) : null}

          {listings.isLoading ? <p className="loading-state">Loading listings…</p> : null}

          {!listings.isLoading && listings.data?.items.length === 0 ? (
            <div className="empty-state">
              <h2>No listings match these filters</h2>
              <p>Try clearing a filter or broadening your keyword search.</p>
              <button onClick={clearFilters} type="button">
                Clear filters
              </button>
            </div>
          ) : null}

          {listings.data?.items.length ? (
            <ol className="listing-results">
              {listings.data.items.map((listing) => (
                <li key={listing.source_id}>
                  <article className="listing-card">
                    <ListingImage alt="" imageUrls={listing.image_urls} />
                    <div className="listing-card__main">
                      <div className="listing-card__heading">
                        <h2>
                          <Link to={listingPath(listing.source_id, searchParameters.toString())}>
                            {listing.title}
                          </Link>
                        </h2>
                        <StatusBadge status={listing.status} />
                      </div>
                      <dl className="listing-facts">
                        <div>
                          <dt>Current bid</dt>
                          <dd>{currency(listing.current_bid)}</dd>
                        </div>
                        <div>
                          <dt>Bid count</dt>
                          <dd>{bidCount(listing.bid_count)}</dd>
                        </div>
                        <div>
                          <dt>Location</dt>
                          <dd>{listing.location ?? "Not available"}</dd>
                        </div>
                        <div>
                          <dt>Closing</dt>
                          <dd>
                            {listing.closing_at ? (
                              <time dateTime={listing.closing_at}>{pacificDateTime(listing.closing_at)}</time>
                            ) : (
                              "Not available"
                            )}
                          </dd>
                        </div>
                      </dl>
                      {isPastClosing(listing) ? (
                        <p className="closing-passed">Closing time passed. Open in latest data.</p>
                      ) : null}
                      <div className="listing-links">
                        <Link to={listingPath(listing.source_id, searchParameters.toString())}>View details</Link>
                        <a href={listing.canonical_source_url}>View source listing</a>
                      </div>
                    </div>
                  </article>
                </li>
              ))}
            </ol>
          ) : null}

          {pageInfo && pageInfo.total_pages > 1 ? (
            <nav aria-label="Listing pages" className="pagination">
              <button
                disabled={pageInfo.page <= 1}
                onClick={() => updateSearch({ ...search, page: pageInfo.page - 1 })}
                type="button"
              >
                Previous
              </button>
              <p>
                Page {pageInfo.page} of {pageInfo.total_pages}
              </p>
              <button
                disabled={pageInfo.page >= pageInfo.total_pages}
                onClick={() => updateSearch({ ...search, page: pageInfo.page + 1 })}
                type="button"
              >
                Next
              </button>
            </nav>
          ) : null}
        </div>
      </div>
    </section>
  );
}

export function ListingNotFound() {
  return (
    <section className="not-found">
      <h1>Page not found</h1>
      <p>The page you requested is not available.</p>
      <Link to="/">Browse listings</Link>
    </section>
  );
}

export function isListingNotFound(error: unknown): boolean {
  return error instanceof ApiRequestError && error.status === 404;
}
