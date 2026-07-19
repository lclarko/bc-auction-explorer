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
  const latestComplete = scrapeStatus.data?.latest_complete_run;
  const completedAt = latestComplete?.finished_at ?? latestComplete?.started_at;
  const latestDuration = runDuration(latest?.started_at, latest?.finished_at);
  const requestNote = latest
    ? ` ${latest.source_requests} source ${latest.source_requests === 1 ? "request" : "requests"}, ${latest.source_retries} ${latest.source_retries === 1 ? "retry" : "retries"}.`
    : "";
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
              Latest run: <strong>{latest.status}</strong>. Last complete refresh: {pacificDateTime(completedAt)}.
              {latestDuration ? ` Completed in ${latestDuration}.` : ""}
              {requestNote}
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

function runDuration(startedAt: string | undefined, finishedAt: string | null | undefined): string | null {
  if (!startedAt || !finishedAt) {
    return null;
  }
  const durationMilliseconds = Date.parse(finishedAt) - Date.parse(startedAt);
  if (!Number.isFinite(durationMilliseconds) || durationMilliseconds < 0) {
    return null;
  }
  const totalSeconds = Math.round(durationMilliseconds / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
}
