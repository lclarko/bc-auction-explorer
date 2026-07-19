import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";

import {
  ApiRequestError,
  getCategories,
  getListings,
  getLocations,
  type ListingSummary,
  type ListingView,
} from "../api/client";
import { ListingImage } from "../components/ListingImage";
import { StatusBadge } from "../components/StatusBadge";
import { bidCount, currency } from "../lib/format";
import {
  defaultListingSearch,
  effectiveListingSort,
  listingQuery,
  listingSearchParams,
  parseListingSearch,
  sortLabels,
  withFirstPage,
  type ListingSearch,
} from "../lib/search";
import { listingInventoryText, listingLifecycleText, pacificDateTime, useLifecycleClock } from "../lib/time";

const viewContent: Record<
  ListingView,
  { description: string; emptyHeading: string; emptyText: string; heading: string; label: string }
> = {
  active: {
    description: "Listings that are still active based on their latest indexed status and closing time.",
    emptyHeading: "No active auctions match these filters",
    emptyText: "Try clearing a filter or broadening your keyword search.",
    heading: "Browse active auction listings",
    label: "Active",
  },
  ended: {
    description: "Listings that have ended or have passed their listed closing time.",
    emptyHeading: "No ended auctions match these filters",
    emptyText: "Try clearing a filter or broadening your keyword search.",
    heading: "Browse ended auction listings",
    label: "Ended",
  },
  all: {
    description: "All listings currently stored in the local index.",
    emptyHeading: "No auction listings match these filters",
    emptyText: "Try clearing a filter or broadening your keyword search.",
    heading: "Browse all indexed auction listings",
    label: "All",
  },
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function listingResultLabel(count: number): string {
  return `${count} ${count === 1 ? "listing" : "listings"}`;
}

function hasCrossedClosingBoundary(listing: ListingSummary, from: number, to: number): boolean {
  if (listing.availability !== "active" || !listing.closing_at) {
    return false;
  }
  const closingAt = Date.parse(listing.closing_at);
  return Number.isFinite(closingAt) && from < closingAt && closingAt <= to;
}

function listingPath(sourceId: string, search: string): string {
  const from = search ? `?from=${encodeURIComponent(search)}` : "";
  return `/listings/${encodeURIComponent(sourceId)}${from}`;
}

export function ListingBrowserPage() {
  const [searchParameters, setSearchParameters] = useSearchParams();
  const rawSearchParameterString = searchParameters.toString();
  const search = parseListingSearch(searchParameters);
  const canonicalSearchParameterString = listingSearchParams(search).toString();
  const currentView = viewContent[search.view];
  const [draft, setDraft] = useState<ListingSearch>(search);
  const [formError, setFormError] = useState<string | null>(null);
  const [resultsNeedRefresh, setResultsNeedRefresh] = useState(false);
  const now = useLifecycleClock();
  const lastVisibleLifecycleCheck = useRef(now);
  const resultsNeedRefreshRef = useRef(false);

  useEffect(() => {
    document.title = `${currentView.heading} | BC Auction Explorer`;
    setDraft(search);
    resultsNeedRefreshRef.current = false;
    setResultsNeedRefresh(false);
    lastVisibleLifecycleCheck.current = Date.now();
  }, [currentView.heading, rawSearchParameterString]);

  const listings = useQuery({
    queryKey: ["listings", search],
    queryFn: ({ signal }) => getListings(listingQuery(search), signal),
    placeholderData: keepPreviousData,
  });
  const locations = useQuery({
    queryKey: ["locations", search.view],
    queryFn: ({ signal }) => getLocations(search.view, signal),
    staleTime: 300_000,
  });
  const categories = useQuery({
    queryKey: ["categories", search.view],
    queryFn: ({ signal }) => getCategories(search.view, signal),
    staleTime: 300_000,
  });

  const updateSearch = (next: ListingSearch): void => {
    setSearchParameters(listingSearchParams(next));
  };

  useEffect(() => {
    if (rawSearchParameterString !== canonicalSearchParameterString) {
      setSearchParameters(canonicalSearchParameterString, { replace: true });
    }
  }, [canonicalSearchParameterString, rawSearchParameterString, setSearchParameters]);

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

  const refreshResults = useCallback((): void => {
    const restoreNoticeOnFailure = resultsNeedRefreshRef.current;
    resultsNeedRefreshRef.current = false;
    setResultsNeedRefresh(false);
    void Promise.all([listings.refetch(), locations.refetch(), categories.refetch()]).then(
      ([listingResult]) => {
        if (listingResult.isError && restoreNoticeOnFailure) {
          resultsNeedRefreshRef.current = true;
          setResultsNeedRefresh(true);
        }
      },
    );
  }, [categories, listings, locations]);

  const checkForVisibleCrossing = useCallback(
    (checkedAt: number): boolean => {
      if (document.visibilityState !== "visible") {
        return false;
      }
      const previous = lastVisibleLifecycleCheck.current;
      if (!listings.data || listings.isPlaceholderData) {
        return false;
      }
      lastVisibleLifecycleCheck.current = checkedAt;
      return (
        search.view === "active" &&
        checkedAt > previous &&
        listings.data.items.some((listing) =>
          hasCrossedClosingBoundary(listing, previous, checkedAt),
        )
      );
    },
    [listings.data?.items, listings.isPlaceholderData, search.view],
  );

  useEffect(() => {
    if (checkForVisibleCrossing(now)) {
      resultsNeedRefreshRef.current = true;
      setResultsNeedRefresh(true);
    }
  }, [checkForVisibleCrossing, now]);

  useEffect(() => {
    const onFocus = (): void => {
      const crossedWhileHidden = checkForVisibleCrossing(Date.now());
      if (crossedWhileHidden || resultsNeedRefreshRef.current) {
        refreshResults();
      }
    };
    const onVisibilityChange = (): void => {
      if (document.visibilityState === "visible") {
        onFocus();
      }
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [checkForVisibleCrossing, refreshResults]);

  const pageInfo = listings.data?.page_info;
  const resultCount = pageInfo?.total_items ?? 0;
  const isUpdating = listings.isPlaceholderData;
  const isRefreshing = listings.isFetching && !listings.isLoading && !isUpdating;
  const selectedSort = effectiveListingSort(search);

  return (
    <section className="listing-browser" aria-labelledby="browse-title">
      <div className="intro">
        <p className="eyebrow">Public auction listings</p>
        <h1 id="browse-title">{currentView.heading}</h1>
        <p>{currentView.description}</p>
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
                Show
                <select
                  onChange={(event) => updateDraft("view", event.target.value as ListingSearch["view"])}
                  value={draft.view}
                >
                  <option value="active">Active auctions</option>
                  <option value="ended">Ended auctions</option>
                  <option value="all">All auctions</option>
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
              <p className="facet-note">
                Location and category counts cover {currentView.label.toLowerCase()} listings.
              </p>
            </form>
          </details>
        </div>

        <div className="results-column">
          <div className="results-toolbar">
            <p aria-live="polite" className="result-count" role="status">
              {listings.isLoading
                ? "Loading listings"
                : isUpdating
                  ? "Updating listings"
                  : isRefreshing
                    ? "Refreshing listings"
                    : listingResultLabel(resultCount)}
            </p>
            <label className="sort-control">
              Sort by
              <select
                onChange={(event) => {
                  const sort = event.target.value as ListingSearch["sort"];
                  updateSearch(withFirstPage({ ...search, sort }));
                }}
                value={selectedSort}
              >
                {Object.entries(sortLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {resultsNeedRefresh ? (
            <div className="refresh-notice">
              <p role="status">Some active listings have reached their scheduled closing time.</p>
              <button disabled={listings.isFetching} onClick={refreshResults} type="button">
                Refresh results
              </button>
            </div>
          ) : null}

          {listings.isError ? (
            <div className="error-panel" role="alert">
              <h2>Listings are unavailable</h2>
              <p>{errorMessage(listings.error)}</p>
              <button onClick={refreshResults} type="button">
                Try again
              </button>
            </div>
          ) : null}

          {listings.isLoading ? <p className="loading-state">Loading listings…</p> : null}

          {!listings.isLoading && !isUpdating && listings.data?.items.length === 0 ? (
            <div className="empty-state">
              <h2>{currentView.emptyHeading}</h2>
              <p>{currentView.emptyText}</p>
              <button onClick={clearFilters} type="button">
                Clear filters
              </button>
            </div>
          ) : null}

          {listings.data?.items.length ? (
            <ol className="listing-results">
              {listings.data.items.map((listing) => {
                const lifecycleText = listing.availability
                  ? listingLifecycleText(
                      listing.availability,
                      listing.status,
                      listing.closing_at,
                      listing.last_seen_at,
                      now,
                    )
                  : null;
                const inventoryText = listingInventoryText(listing.inventory_state);
                return (
                  <li key={listing.source_id}>
                    <article className="listing-card">
                      <ListingImage alt="" imageUrls={listing.image_urls} />
                      <div className="listing-card__main">
                        <div className="listing-card__heading">
                          <h2>
                            <Link to={listingPath(listing.source_id, canonicalSearchParameterString)}>
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
                        {lifecycleText ? <p className="closing-passed">{lifecycleText}</p> : null}
                        {inventoryText ? <p className="closing-passed">{inventoryText}</p> : null}
                        <div className="listing-links">
                          <Link to={listingPath(listing.source_id, canonicalSearchParameterString)}>View details</Link>
                          <a href={listing.canonical_source_url}>View source listing</a>
                        </div>
                      </div>
                    </article>
                  </li>
                );
              })}
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
