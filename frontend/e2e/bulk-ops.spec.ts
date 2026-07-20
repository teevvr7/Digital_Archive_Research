import { test, expect } from "@playwright/test";
import path from "path";
import { hasCreds, SKIP_REASON, permanentlyDeleteByFilename } from "./helpers";

const FILENAME = "e2e-bulk-ops.pdf";
const FIXTURE = path.join(__dirname, "fixtures", FILENAME);
const TAG_NAME = `E2E Bulk Tag ${Date.now()}`;

test.describe("bulk operations", () => {
  test.skip(!hasCreds, SKIP_REASON);

  test("bulk tag shows a success toast; bulk trash opens a danger confirm and removes the row", async ({
    page,
  }) => {
    // Setup: a tag to assign (the bulk-tag toolbar button only renders once
    // the tenant has at least one tag) and a document to act on.
    await page.goto("/tags");
    await page.getByRole("button", { name: "New tag" }).click();
    await page.getByPlaceholder("e.g. Invoices").fill(TAG_NAME);
    await page.getByRole("button", { name: "Create tag" }).click();
    await expect(page.getByText(TAG_NAME)).toBeVisible();

    await page.goto("/upload");
    await page.locator('input[type="file"]:not([capture])').setInputFiles(FIXTURE);
    await page.getByRole("button", { name: /Upload \d+ file/ }).click();
    await page.waitForURL("**/documents", { timeout: 30_000 });
    await expect(page.getByText(FILENAME).first()).toBeVisible({ timeout: 15_000 });

    // Select the row and bulk-assign the tag.
    const row = page.locator("tr", { hasText: FILENAME }).first();
    await row.locator('input[type="checkbox"]').check();
    await page.getByTestId("bulk-tag-button").click();
    // "Assign" buttons render before "Remove" buttons in the same menu.
    await page.getByRole("button", { name: TAG_NAME }).first().click();
    await expect(page.getByText(/Tag assigned to 1 document/i)).toBeVisible({ timeout: 10_000 });

    // Re-select (the list re-renders after the bulk action) and bulk-trash.
    await row.locator('input[type="checkbox"]').check();
    await page.getByTestId("bulk-trash-button").click();
    await expect(page.getByTestId("confirm-dialog")).toBeVisible();
    await expect(page.getByText(/Move .* to trash/i)).toBeVisible();
    await page.getByTestId("confirm-dialog-confirm").click();

    await expect(page.getByText(/Moved 1 document.*trash/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.locator("tr", { hasText: FILENAME })).toHaveCount(0);

    // Cleanup: free the checksum + remove the throwaway tag.
    await permanentlyDeleteByFilename(page, FILENAME);
    await page.goto("/tags");
    await page.locator("tr", { hasText: TAG_NAME }).getByTitle("Delete").click();
    await page.getByTestId("confirm-dialog-confirm").click();
  });
});
