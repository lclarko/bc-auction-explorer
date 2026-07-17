import { TZDate } from "@date-fns/tz";

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

export function pacificDateTime(value: string | null | undefined): string {
  if (!value || Number.isNaN(new Date(value).getTime())) {
    return "Not available";
  }
  return `${dateFormatter.format(new Date(value))} PT`;
}

export function pacificDate(value: string | null | undefined): string {
  if (!value || Number.isNaN(new Date(value).getTime())) {
    return "Not available";
  }
  return `${dateOnlyFormatter.format(new Date(value))} PT`;
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
