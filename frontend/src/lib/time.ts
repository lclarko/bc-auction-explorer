import { useEffect, useState } from "react";

import { TZDate } from "@date-fns/tz";

import type { AuctionStatus, InventoryState, ListingAvailability } from "../api/client";

export const PACIFIC_TIME_ZONE = "America/Vancouver";

const dateFormatter = new Intl.DateTimeFormat("en-CA", {
  dateStyle: "medium",
  timeZone: PACIFIC_TIME_ZONE,
  timeStyle: "short",
});

const dateOnlyFormatter = new Intl.DateTimeFormat("en-CA", {
  dateStyle: "medium",
  timeZone: PACIFIC_TIME_ZONE,
});

const timeZoneNameFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: PACIFIC_TIME_ZONE,
  timeZoneName: "short",
});

function parsedDate(value: string | null | undefined): Date | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function pacificTimeZoneName(date: Date): string {
  const zoneName = timeZoneNameFormatter
    .formatToParts(date)
    .find((part) => part.type === "timeZoneName")?.value;
  return zoneName === "PST" || zoneName === "PDT" ? zoneName : "Pacific time";
}

export function pacificDateTime(value: string | null | undefined): string {
  const date = parsedDate(value);
  if (!date) {
    return "Not available";
  }
  return `${dateFormatter.format(date)} ${pacificTimeZoneName(date)}`;
}

export function pacificDate(value: string | null | undefined): string {
  const date = parsedDate(value);
  if (!date) {
    return "Not available";
  }
  return `${dateOnlyFormatter.format(date)} ${pacificTimeZoneName(date)}`;
}

function relativeDuration(milliseconds: number): string {
  const absoluteMilliseconds = Math.abs(milliseconds);
  if (absoluteMilliseconds < 60_000) {
    return "less than a minute";
  }
  const totalMinutes = Math.ceil(absoluteMilliseconds / 60_000);
  if (totalMinutes < 60) {
    return `${totalMinutes} ${totalMinutes === 1 ? "minute" : "minutes"}`;
  }
  if (totalMinutes >= 24 * 60) {
    const days = Math.floor(totalMinutes / (24 * 60));
    const remainderMinutes = totalMinutes % (24 * 60);
    const hours = Math.floor(remainderMinutes / 60);
    const minutes = remainderMinutes % 60;
    const parts = [`${days} ${days === 1 ? "day" : "days"}`];
    if (hours) {
      parts.push(`${hours} ${hours === 1 ? "hour" : "hours"}`);
    }
    if (minutes) {
      parts.push(`${minutes} ${minutes === 1 ? "minute" : "minutes"}`);
    }
    return parts.join(" ");
  }
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  const hourText = `${hours} ${hours === 1 ? "hour" : "hours"}`;
  return minutes ? `${hourText} ${minutes} ${minutes === 1 ? "minute" : "minutes"}` : hourText;
}

function unsupportedAvailability(value: never): never {
  throw new Error(`Unsupported listing availability: ${value}`);
}

export function listingLifecycleText(
  availability: ListingAvailability,
  sourceStatus: AuctionStatus,
  closingAt: string | null | undefined,
  lastSeenAt: string | null | undefined,
  now = Date.now(),
): string | null {
  const closingDate = parsedDate(closingAt);
  const closingHasPassed = closingDate !== null && closingDate.getTime() <= now;
  if (
    availability === "scheduled_closing_passed" ||
    (availability === "active" && sourceStatus === "open" && closingHasPassed)
  ) {
    const passedText = closingDate
      ? `Scheduled closing time passed ${relativeDuration(now - closingDate.getTime())} ago.`
      : "Scheduled closing time passed.";
    return lastSeenAt
      ? `${passedText} Last observed open at ${pacificDateTime(lastSeenAt)}.`
      : passedText;
  }

  switch (availability) {
    case "active": {
      if (!closingDate) {
        return "Closing time unavailable.";
      }
      return `Closes in ${relativeDuration(closingDate.getTime() - now)}.`;
    }
    case "closed":
    case "withdrawn":
      return null;
    case "unknown":
      return sourceStatus === "open" ? "Closing time unavailable." : null;
    default:
      return unsupportedAvailability(availability);
  }
}

export function listingInventoryText(inventoryState: InventoryState | undefined): string | null {
  switch (inventoryState) {
    case undefined:
    case "current":
      return null;
    case "not_observed":
      return "Not found in the latest complete refresh.";
    case "stale":
      return "Stale or unavailable.";
    default:
      throw new Error(`Unsupported inventory state: ${inventoryState}`);
  }
}

export function useLifecycleClock(): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let timeout: number | undefined;
    const scheduleNextMinute = (): void => {
      const current = Date.now();
      const delay = 60_000 - (current % 60_000);
      timeout = window.setTimeout(() => {
        setNow(Date.now());
        scheduleNextMinute();
      }, delay);
    };
    scheduleNextMinute();
    return () => {
      if (timeout !== undefined) {
        window.clearTimeout(timeout);
      }
    };
  }, []);

  return now;
}

export function dateInputToUtc(value: string, boundary: "start" | "end"): string | undefined {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) {
    return undefined;
  }
  const [, yearText, monthText, dayText] = match;
  const year = Number(yearText);
  const month = Number(monthText) - 1;
  const day = Number(dayText);
  const date =
    boundary === "start"
      ? TZDate.tz(PACIFIC_TIME_ZONE, year, month, day, 0, 0, 0, 0)
      : TZDate.tz(PACIFIC_TIME_ZONE, year, month, day, 23, 59, 59, 999);
  return new Date(date.getTime()).toISOString();
}
