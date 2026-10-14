// Specification section 12, tier 3, spec 2:
// "Open a lead → timeline newest first → add a note with a follow-up later today
//  → the lead moves into Today's follow-ups."

import { expect, test } from "@playwright/test";
import { formatInTimeZone } from "date-fns-tz";

import { APP_TIMEZONE } from "./env";

// Seeded by scripts.seed (reset in global setup): two notes, follow-up tomorrow,
// so the lead starts under "All leads".
const LEAD = "Daniel Ferreira";
const NEWER_NOTE = "Emailed an introduction; Daniel asked for a short call in the morning.";
const OLDER_NOTE = "Referred by an existing customer. Runs four outpatient clinics.";

const MINUTE = 60_000;

/** A follow-up 5 minutes from now in the app timezone, or null too close to midnight. */
function laterToday(now: Date) {
  const at = new Date(Math.floor((now.getTime() + 5 * MINUTE) / MINUTE) * MINUTE);
  const today = formatInTimeZone(now, APP_TIMEZONE, "yyyy-MM-dd");
  // Same 10-minute margin as the seed script: past it there is no "later today".
  if (formatInTimeZone(new Date(at.getTime() + 10 * MINUTE), APP_TIMEZONE, "yyyy-MM-dd") !== today) {
    return null;
  }
  return {
    date: formatInTimeZone(at, APP_TIMEZONE, "yyyy-MM-dd"),
    time: formatInTimeZone(at, APP_TIMEZONE, "HH:mm"),
    clock: formatInTimeZone(at, APP_TIMEZONE, "h:mm a"), // "11:35 PM"
    dayAndClock: formatInTimeZone(at, APP_TIMEZONE, "MMM d, h:mm a"), // "Oct 14, 11:35 PM"
  };
}

test("a note with a follow-up later today moves the lead into Today's follow-ups", async ({
  page,
}) => {
  const later = laterToday(new Date());
  test.skip(
    later === null,
    "Within 10 minutes of midnight in the app timezone; the backend's fixed-clock tests cover this.",
  );
  if (later === null) return;

  await page.goto("/");
  const today = page.getByRole("region", { name: /^Today's follow-ups/ });
  const allLeads = page.getByRole("region", { name: /^All leads/ });
  const card = (section: typeof today) => section.getByRole("button", { name: new RegExp(`^${LEAD}`) });

  // Before: listed under All leads, not under Today.
  await expect(card(allLeads)).toBeVisible();
  await expect(card(today)).toHaveCount(0);

  // Open the lead: the timeline is newest first, ending with "Lead created".
  await card(allLeads).click();
  const dialog = page.getByRole("dialog", { name: new RegExp(`^${LEAD}`) });
  const entries = dialog.getByRole("listitem");
  await expect(entries).toHaveCount(3);
  await expect(entries.nth(0)).toContainText(NEWER_NOTE);
  await expect(entries.nth(1)).toContainText(OLDER_NOTE);
  await expect(entries.nth(2)).toContainText("Lead created");

  // Add a note with a follow-up later today (wall-clock time in IST).
  const note = `E2E: confirmed a call later today (${Date.now()}).`;
  await dialog.getByLabel("New discussion note").fill(note);
  await dialog.getByLabel("Set Follow-up").check();
  await dialog.getByLabel(/^Follow-up date/).fill(later.date);
  await dialog.getByLabel(/^Follow-up time/).fill(later.time);
  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" && /\/api\/leads\/\d+\/discussions$/.test(response.url()),
  );
  await dialog.getByRole("button", { name: "Save Note" }).click();
  expect((await saved).status()).toBe(201);

  // The new note is first, records its follow-up, and the header shows it.
  await expect(entries).toHaveCount(4);
  await expect(entries.nth(0)).toContainText(note);
  await expect(entries.nth(0)).toContainText(`Follow-up set for: ${later.dayAndClock}`);
  await expect(entries.nth(1)).toContainText(NEWER_NOTE);
  await expect(dialog.getByText(`Today, ${later.clock}`, { exact: true })).toBeVisible();

  // After: the lead has moved into Today's follow-ups (and out of All leads).
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(card(today)).toBeVisible();
  await expect(card(allLeads)).toHaveCount(0);
  await expect(
    today.getByRole("article", { name: new RegExp(`^${LEAD}`) }).getByText(
      `Follow-up today at ${later.clock}`,
    ),
  ).toBeVisible();
});
