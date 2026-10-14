// Specification section 12, tier 3, spec 3:
// "Change status → reload → status persisted."

import { expect, test } from "@playwright/test";

// Seeded by scripts.seed (reset in global setup) with status New.
const LEAD = "Aisha Karim";
const NAME = new RegExp(`^${LEAD}`);

test("a status change survives a page reload", async ({ page }) => {
  await page.goto("/");
  const card = page.getByRole("article", { name: NAME });
  await expect(card.getByText("New", { exact: true })).toBeVisible();

  // Change the status in the timeline dialog; it is saved by PATCH.
  await card.getByRole("button", { name: NAME }).click();
  const dialog = page.getByRole("dialog", { name: NAME });
  const status = dialog.getByLabel("Status");
  await expect(status).toHaveValue("new");

  const patched = page.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" && /\/api\/leads\/\d+$/.test(response.url()),
  );
  await status.selectOption("contacted");
  const response = await patched;
  expect(response.status()).toBe(200);
  expect((await response.json()).status).toBe("contacted");
  await expect(status).toBeEnabled(); // the save has settled
  await expect(status).toHaveValue("contacted");

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();

  // Reload: the card and a freshly fetched dialog both show the saved status.
  await page.reload();
  const reloaded = page.getByRole("article", { name: NAME });
  await expect(reloaded.getByText("Contacted", { exact: true })).toBeVisible();
  await expect(reloaded.getByText("New", { exact: true })).toHaveCount(0);

  await reloaded.getByRole("button", { name: NAME }).click();
  await expect(page.getByRole("dialog", { name: NAME }).getByLabel("Status")).toHaveValue(
    "contacted",
  );
});
