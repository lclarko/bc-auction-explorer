import type { ReactNode } from "react";

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { getScrapeStatus } from "../api/client";
import { pacificDateTime } from "../lib/time";

export function AppShell({ children }: { children: ReactNode }) {
  const scrapeStatus = useQuery({
    queryKey: ["scrape-status"],
    queryFn: ({ signal }) => getScrapeStatus(signal),
    staleTime: 60_000,
  });
  const latest = scrapeStatus.data?.latest_run;
  const latestSuccess = scrapeStatus.data?.latest_successful_run;
  const successfulAt = latestSuccess?.finished_at ?? latestSuccess?.started_at;
  const latestRunNote =
    latest?.status === "partial"
      ? ` ${latest.item_failures} ${latest.item_failures === 1 ? "listing" : "listings"} could not be stored.`
      : latest?.status === "failed"
        ? " The latest run did not complete."
        : "";

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to results
      </a>
      <header className="site-header">
        <div className="page-width site-header__content">
          <Link className="site-title" to="/">
            BC Auction Explorer
          </Link>
          <p className="unofficial-label">Unofficial project</p>
        </div>
        <div className="page-width freshness" role="status">
          {scrapeStatus.isError ? (
            "Refresh status is temporarily unavailable."
          ) : scrapeStatus.isLoading ? (
            "Loading refresh status."
          ) : latest ? (
            <>
              Latest run: <strong>{latest.status}</strong>. Last successful refresh: {pacificDateTime(successfulAt)}.
              {latestRunNote}
            </>
          ) : (
            "No scrape run has been recorded yet."
          )}
        </div>
      </header>
      <main className="page-width" id="main-content">
        {children}
      </main>
      <footer className="site-footer page-width">
        Listings are indexed from public BC Auction pages. The original source listing is authoritative.
      </footer>
    </div>
  );
}
