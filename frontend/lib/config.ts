// NEXT_PUBLIC_* values are inlined into the browser bundle when Next.js
// builds or serves the app, so this must be a URL the *browser* can reach.
const DEVELOPMENT_API_URL = "http://localhost:8000";

/**
 * Base URL of the FastAPI backend, without a trailing slash.
 *
 * Set NEXT_PUBLIC_API_URL. Only `next dev` falls back to the local backend;
 * a production build without it fails loudly instead of silently calling
 * localhost from a user's browser.
 */
export function getApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (configured) {
    return configured.replace(/\/+$/, "");
  }
  if (process.env.NODE_ENV !== "production") {
    return DEVELOPMENT_API_URL;
  }
  throw new Error("NEXT_PUBLIC_API_URL is not set; it is required for production builds.");
}

const DEFAULT_APP_TIMEZONE = "Asia/Kolkata";

/**
 * IANA timezone used for "today", follow-up labels and every displayed time,
 * independent of the browser's own timezone. It must equal the backend's
 * APP_TIMEZONE; Docker Compose sets NEXT_PUBLIC_APP_TIMEZONE from that value.
 */
export function getAppTimezone(): string {
  const configured = process.env.NEXT_PUBLIC_APP_TIMEZONE?.trim() || DEFAULT_APP_TIMEZONE;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: configured });
  } catch {
    throw new Error(`NEXT_PUBLIC_APP_TIMEZONE is not a valid IANA timezone: ${configured}`);
  }
  return configured;
}
