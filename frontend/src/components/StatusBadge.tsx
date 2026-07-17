import type { AuctionStatus } from "../api/client";

export function StatusBadge({ status }: { status: AuctionStatus }) {
  return <span className={`status-badge status-badge--${status}`}>{status}</span>;
}
