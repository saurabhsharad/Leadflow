// Date and time display in the application timezone (spec section 6): never
// the browser's default timezone. Classification (due today / overdue) comes
// from the API's flags; these helpers only format.

import { differenceInCalendarDays, parseISO } from "date-fns";
import { formatInTimeZone } from "date-fns-tz";

import type { IsoDateTime } from "@/lib/types";

type Instant = Date | IsoDateTime;

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

function toDate(value: Instant): Date {
  return typeof value === "string" ? new Date(value) : value;
}

/** Calendar days from `now` to `value` in `tz` (0 = today, -1 = yesterday, 1 = tomorrow). */
export function calendarDaysFrom(value: Instant, now: Date, tz: string): number {
  const day = (d: Date) => parseISO(formatInTimeZone(d, tz, "yyyy-MM-dd"));
  return differenceInCalendarDays(day(toDate(value)), day(now));
}

/** "2:00 PM" in `tz`. */
export function formatAppTime(value: Instant, tz: string): string {
  return formatInTimeZone(toDate(value), tz, "h:mm a");
}

/** "Oct 16", with the year only when it differs from the current year in `tz`. */
export function formatAppDate(value: Instant, now: Date, tz: string): string {
  const date = toDate(value);
  const sameYear = formatInTimeZone(date, tz, "yyyy") === formatInTimeZone(now, tz, "yyyy");
  return formatInTimeZone(date, tz, sameYear ? "MMM d" : "MMM d, yyyy");
}

/** "Today", "Tomorrow", "Yesterday" or "Oct 16" for the calendar day of `value` in `tz`. */
export function formatAppDay(value: Instant, now: Date, tz: string): string {
  const days = calendarDaysFrom(value, now, tz);
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  if (days === -1) return "Yesterday";
  return formatAppDate(value, now, tz);
}

/**
 * "just now", "5 min ago", "3 hours ago", "yesterday", "4 days ago", then the
 * date after 7 days (spec section 6).
 */
export function relativeTime(value: Instant, now: Date, tz: string): string {
  const elapsed = now.getTime() - toDate(value).getTime();
  if (elapsed < MINUTE) return "just now";
  if (elapsed < HOUR) return `${Math.floor(elapsed / MINUTE)} min ago`;
  if (elapsed < 24 * HOUR) {
    const hours = Math.floor(elapsed / HOUR);
    return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  }
  const days = -calendarDaysFrom(value, now, tz);
  if (days <= 1) return "yesterday";
  if (days <= 7) return `${days} days ago`;
  return formatAppDate(value, now, tz);
}
