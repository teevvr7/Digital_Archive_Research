import { test, expect } from "@playwright/test";
import path from "path";
import { hasCreds, SKIP_REASON, permanentlyDeleteByFilename } from "./helpers";

const FILENAME = "e2e-filter-invoice.pdf";
const FIXTURE = path.join(__dirname, "fixtures", FILENAME);
const FIELD_NAME = `E2E Order Number ${Date.now()}`;

// A single, self-contained golden path: create a custom field, predefine it
// for Invoices, set its value while uploading an invoice, then confirm the
// Documents page's type-gated filter (built in the predefined-fields work)
// unlocks only for that type and actually narrows the list.
test.describe("documents custom-field filter", () => {
  test.skip(!hasCreds, SKIP_REASON);

  test("type-gated custom field filter narrows the Documents list", async ({ page }) => {
    // 1. Create a number-type custom field.
    await page.goto("/custom-fields");
    await page.getByRole("button", { name: "New field" }).click();
    await page.getByTestId("new-field-name").fill(FIELD_NAME);
    await page.getByTestId("new-field-type").selectOption("number");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(FIELD_NAME)).toBeVisible();

    // 2. Predefine it for Invoices.
    const invoiceCard = page.getByTestId("predefined-card-invoice");
    await invoiceCard.getByTestId("predefined-add-open-invoice").click();
    await page.getByTestId("predefined-picker-invoice").selectOption({ label: FIELD_NAME });
    await page.getByTestId("predefined-confirm-invoice").click();
    await expect(invoiceCard.getByText(FIELD_NAME)).toBeVisible();

    // 3. Upload an invoice and fill in the field's value.
    await page.goto("/upload");
    await page.getByRole("button", { name: "Invoice", exact: true }).click();
    await page.locator('input[type="file"]:not([capture])').setInputFiles(FIXTURE);
    await page.getByTitle("Fill in details for this file").click();
    await page
      .getByTestId(`predefined-field-input-${FIELD_NAME}`)
      .fill("78945");
    await page.getByRole("button", { name: "Save details" }).click();
    await page.getByRole("button", { name: /Upload \d+ file/ }).click();
    await page.waitForURL("**/documents", { timeout: 30_000 });

    // 4. Filter: Type=Invoice unlocks the custom-field picker.
    await page.getByTestId("type-filter").selectOption("invoice");
    await expect(page.getByTestId("custom-field-picker")).toBeVisible();
    await page.getByTestId("custom-field-picker").selectOption({ label: FIELD_NAME });

    // Number fields default to "Contains" — search by a few digits.
    await page.getByPlaceholder("Contains…").fill("789");
    await expect(page.getByText(FILENAME).first()).toBeVisible({ timeout: 15_000 });

    // A value that isn't a substring of "78945" must not match.
    await page.getByPlaceholder("Contains…").fill("111");
    await expect(page.getByText(FILENAME)).not.toBeVisible();

    // 5. Switching to a type with no predefined fields hides the picker again.
    await page.getByTestId("type-filter").selectOption("receipt");
    await expect(page.getByTestId("custom-field-picker")).not.toBeVisible();

    // Cleanup: remove the document (frees the checksum for re-runs) and the
    // custom field (avoids piling up throwaway fields on repeated runs).
    await permanentlyDeleteByFilename(page, FILENAME);
    await page.goto("/custom-fields");
    await page
      .locator("tr", { hasText: FIELD_NAME })
      .getByTitle("Delete")
      .click();
    await page.getByTestId("confirm-dialog-confirm").click();
  });
});
