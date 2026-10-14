// Date and time display in the application timezone (spec section 6): never
// the browser's default timezone. Classification (due today / overdue) comes
// from the API's flags; these helpers only format.

import { differenceInCalendarDays, parseISO } from "date-fns";
import { formatInTimeZone, fromZonedTime } from "date-fns-tz";

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

/** "May 4, 10:30 AM" in `tz`, with the year only when it differs from the current year. */
export function formatAppDateTime(value: Instant, now: Date, tz: string): string {
  return `${formatAppDate(value, now, tz)}, ${formatAppTime(value, tz)}`;
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

const DATE_INPUT = /^\d{4}-\d{2}-\d{2}$/;
const TIME_INPUT = /^\d{2}:\d{2}$/;

/**
 * The instant for a wall-clock date ("2026-10-14") and time ("14:00") as read
 * in `tz`, whatever the browser's own timezone is. Returns an ISO string in UTC
 * ("...Z", which the API accepts as an offset), or null for incomplete or
 * impossible values.
 */
export function toAppInstant(date: string, time: string, tz: string): IsoDateTime | null {
  if (!DATE_INPUT.test(date) || !TIME_INPUT.test(time)) return null;
  const instant = fromZonedTime(`${date}T${time}:00`, tz);
  if (Number.isNaN(instant.getTime())) return null;
  // Reject values that do not round-trip: impossible dates such as "2026-02-30"
  // (otherwise read as March 2) and wall-clock times skipped by a DST change.
  if (formatInTimeZone(instant, tz, "yyyy-MM-dd'T'HH:mm") !== `${date}T${time}`) return null;
  return instant.toISOString();
}

/** Short label for the inputs: "IST" for the default timezone, otherwise its IANA name. */
export function timezoneLabel(tz: string): string {
  return tz === "Asia/Kolkata" ? "IST" : tz;
}
