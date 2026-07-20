import { test, expect } from "@playwright/test";
import path from "path";
import { hasCreds, SKIP_REASON, permanentlyDeleteByFilename } from "./helpers";

const FILENAME = "e2e-sample-invoice.pdf";
const FIXTURE = path.join(__dirname, "fixtures", FILENAME);

test.describe("upload", () => {
  test.skip(!hasCreds, SKIP_REASON);

  test("uploading a file makes it appear in the Documents list", async ({ page }) => {
    await page.goto("/upload");

    // Two file inputs exist (regular picker + camera capture) — target the
    // plain one, which has no `capture` attribute.
    await page.locator('input[type="file"]:not([capture])').setInputFiles(FIXTURE);
    await expect(page.getByText(FILENAME)).toBeVisible();

    await page.getByRole("button", { name: /Upload \d+ file/ }).click();

    // The page auto-navigates to /documents once every file reaches a
    // terminal (queued/duplicate) state.
    await page.waitForURL("**/documents", { timeout: 30_000 });

    // Sorted newest-first by default, so the just-uploaded file (title not
    // yet set by the worker, falls back to the original filename) should be
    // visible without needing to search.
    await expect(page.getByText(FILENAME).first()).toBeVisible({ timeout: 15_000 });

    // Clean up so re-running this spec doesn't hit sha256 dedup and skip
    // creating a fresh document next time.
    await permanentlyDeleteByFilename(page, FILENAME);
  });
});
