import { defineConfig, devices } from "@playwright/test";

import { BASE_URL } from "./e2e/env";

// End-to-end specs from the specification (section 12, tier 3), run against the
// isolated leadflow-e2e Compose stack. See README.md > End-to-end tests.
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  // The specs share one database and the seed reset, so run them one at a time.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: BASE_URL,
    // A browser timezone far from the app's: every time shown must still be IST.
    timezoneId: "America/New_York",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
