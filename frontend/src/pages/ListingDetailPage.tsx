import { useEffect } from "react";

import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { getListing } from "../api/client";
import { ImageGallery } from "../components/ImageGallery";
import { StatusBadge } from "../components/StatusBadge";
import { bidCount, currency } from "../lib/format";
import { pacificDateTime } from "../lib/time";
import { isListingNotFound } from "./ListingBrowserPage";

function detailErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

export function ListingDetailPage() {
  const { sourceId } = useParams();
  const [searchParameters] = useSearchParams();
  const from = searchParameters.get("from");
  const backTo = from ? `/?${from}` : "/";
  const listing = useQuery({
    enabled: Boolean(sourceId),
    queryKey: ["listing", sourceId],
    queryFn: ({ signal }) => getListing(sourceId ?? "", signal),
  });

  useEffect(() => {
    document.title = listing.data ? `${listing.data.title} | BC Auction Explorer` : "Listing | BC Auction Explorer";
  }, [listing.data]);

  if (!sourceId) {
    return (
      <section className="not-found">
        <h1>Listing not found</h1>
        <Link to={backTo}>Back to listings</Link>
      </section>
    );
  }

  if (listing.isLoading) {
    return <p className="loading-state">Loading listing…</p>;
  }

  if (listing.isError) {
    return (
      <section className="error-panel" role="alert">
        <h1>{isListingNotFound(listing.error) ? "Listing not found" : "Listing is unavailable"}</h1>
        <p>{detailErrorMessage(listing.error)}</p>
        <Link to={backTo}>Back to listings</Link>
      </section>
    );
  }

  const item = listing.data;
  if (!item) {
    return null;
  }

  const location = item.location ?? item.location_raw ?? "Not available";
  const locationDetail = item.location_qualifier ? `${location}, ${item.location_qualifier}` : location;
  const rawLocation =
    item.location_normalization_status === "unknown" && item.location_raw ? item.location_raw : null;

  return (
    <article className="listing-detail">
      <Link className="back-link" to={backTo}>
        Back to listings
      </Link>
      <header className="detail-header">
        <div>
          <p className="eyebrow">Auction listing</p>
          <h1>{item.title}</h1>
        </div>
        <StatusBadge status={item.status} />
      </header>
      <div className="detail-layout">
        <div className="detail-image-wrap">
          <ImageGallery imageUrls={item.image_urls} title={item.title} />
          {item.image_urls.length > 1 ? <p>{item.image_urls.length} public images available</p> : null}
        </div>
        <div>
          <dl className="detail-facts">
            <div>
              <dt>Current bid</dt>
              <dd>{currency(item.current_bid)}</dd>
            </div>
            <div>
              <dt>Minimum bid</dt>
              <dd>{currency(item.minimum_bid)}</dd>
            </div>
            {item.starting_bid !== null && item.starting_bid !== undefined ? (
              <div>
                <dt>Starting bid</dt>
                <dd>{currency(item.starting_bid)}</dd>
              </div>
            ) : null}
            <div>
              <dt>Bid count</dt>
              <dd>{bidCount(item.bid_count)}</dd>
            </div>
            <div>
              <dt>Closing</dt>
              <dd>
                {item.closing_at ? (
                  <time dateTime={item.closing_at}>{pacificDateTime(item.closing_at)}</time>
                ) : (
                  "Not available"
                )}
              </dd>
            </div>
            <div>
              <dt>Location</dt>
              <dd>{locationDetail}</dd>
            </div>
            {rawLocation ? (
              <div>
                <dt>Source location</dt>
                <dd>{rawLocation}</dd>
              </div>
            ) : null}
          </dl>
          <p className="source-link">
            <a href={item.canonical_source_url}>View the source listing</a>
          </p>
        </div>
      </div>

      {item.pickup_details ? (
        <section className="detail-section">
          <h2>Pickup details</h2>
          <p className="preserved-text">{item.pickup_details}</p>
        </section>
      ) : null}
      {item.description ? (
        <section className="detail-section">
          <h2>Description</h2>
          <p className="preserved-text">{item.description}</p>
        </section>
      ) : null}
      <section className="detail-section freshness-detail">
        <h2>Record freshness</h2>
        <p>
          Last observed: <time dateTime={item.last_seen_at}>{pacificDateTime(item.last_seen_at)}</time>
        </p>
      </section>
    </article>
  );
}
