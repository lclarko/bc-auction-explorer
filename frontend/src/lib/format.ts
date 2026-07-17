export function currency(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "Not available";
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "Not available";
  }
  return new Intl.NumberFormat("en-CA", {
    currency: "CAD",
    currencyDisplay: "narrowSymbol",
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
    style: "currency",
  }).format(parsed);
}

export function bidCount(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "Not available";
  }
  return `${value} ${value === 1 ? "bid" : "bids"}`;
}
