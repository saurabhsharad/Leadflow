// NEXT_PUBLIC_* values are inlined into the browser bundle when Next.js
// builds or serves the app, so this must be a URL the *browser* can reach.
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");
