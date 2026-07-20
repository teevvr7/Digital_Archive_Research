import type { Page } from "@playwright/test";

/** True when a dedicated E2E test account is configured via env. Specs use
 * this to skip the whole suite gracefully on a checkout without credentials
 * — mirrors the backend's ALEMBIC_DATABASE_URL-gated integration tests. */
export const hasCreds = Boolean(process.env.E2E_EMAIL && process.env.E2E_PASSWORD);

export const SKIP_REASON = "E2E_EMAIL/E2E_PASSWORD not set — skipping E2E suite";

/**
 * Trash then permanently delete a document by its visible filename, so a
 * spec that uploads a fixture leaves the tenant clean and the fixture's
 * checksum free for the next run — dedup keys off checksum regardless of
 * `deleted_at`, so a soft trash alone would still block re-upload.
 */
export async function permanentlyDeleteByFilename(page: Page, filename: string) {
  await page.goto("/documents");
  const row = page.locator("tr", { hasText: filename }).first();
  if (await row.getByTitle("Move to trash").isVisible().catch(() => false)) {
    await row.getByTitle("Move to trash").click();
  }

  await page.getByRole("button", { name: "Trash", exact: true }).click();
  const trashedRow = page.locator("tr", { hasText: filename }).first();
  await trashedRow.getByTitle("Delete permanently").click();
  await page.getByTestId("confirm-dialog-confirm").click();
}
