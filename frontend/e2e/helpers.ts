import { expect, type Page } from "@playwright/test";

/** True when a dedicated E2E test account is configured via env. Specs use
 * this to skip the whole suite gracefully on a checkout without credentials
 * — mirrors the backend's ALEMBIC_DATABASE_URL-gated integration tests. */
export const hasCreds = Boolean(process.env.E2E_EMAIL && process.env.E2E_PASSWORD);

export const SKIP_REASON = "E2E_EMAIL/E2E_PASSWORD not set — skipping E2E suite";

/**
 * Trash a document by its visible filename, then empty the whole trash, so a
 * spec that uploads a fixture leaves the tenant clean and the fixture's
 * checksum free for the next run — dedup keys off checksum regardless of
 * `deleted_at`, so a soft trash alone would still block re-upload.
 *
 * Empties the *entire* trash rather than hunting for one specific row in the
 * Trash view/table — safe because every spec here runs against a dedicated
 * throwaway E2E tenant with no real trash content to protect, and it sidesteps
 * a real flakiness source: switching to the Trash view right after a trash
 * mutation can be queried before that specific row has rendered there yet.
 */
export async function permanentlyDeleteByFilename(page: Page, filename: string) {
  await page.goto("/documents");
  const row = page.locator("tr", { hasText: filename }).first();
  // A one-shot .isVisible() right after goto() is racy — the list may not
  // have finished its first render/fetch yet, wrongly concluding the doc
  // isn't in the active view. Wait (with retry) instead; if it never shows
  // up, assume it's already trashed (e.g. a prior bulk-trash in the same
  // test) and skip straight to emptying the trash.
  const isActive = await row
    .waitFor({ state: "visible", timeout: 5_000 })
    .then(() => true)
    .catch(() => false);
  if (isActive) {
    await row.getByTitle("Move to trash").click();
    await row.waitFor({ state: "detached", timeout: 10_000 }).catch(() => {});
  }

  await page.goto("/documents");
  await page.getByRole("button", { name: "Trash", exact: true }).click();
  const emptyBtn = page.getByRole("button", { name: "Empty trash" });
  // .isEnabled() alone is a one-shot check (only waits for the element to
  // attach, not for the disabled attribute to actually clear once the
  // Trash view's own fetch resolves) — expect(...).toBeEnabled() is the
  // real poll-until-true assertion.
  const canEmpty = await expect(emptyBtn)
    .toBeEnabled({ timeout: 10_000 })
    .then(() => true)
    .catch(() => false);
  if (!canEmpty) return; // nothing in trash — already clean
  await emptyBtn.click();
  await page.getByTestId("confirm-dialog-confirm").click();
  await page.waitForTimeout(500);
}
