import type { AuctionStatus } from "../api/client";

const statusLabels: Record<AuctionStatus, string> = {
  open: "Open",
  closed: "Closed",
  withdrawn: "Withdrawn",
  unknown: "Unknown",
};

export function StatusBadge({ status }: { status: AuctionStatus }) {
  return <span className={`status-badge status-badge--${status}`}>{statusLabels[status]}</span>;
}
