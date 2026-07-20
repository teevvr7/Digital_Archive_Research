import { test, expect } from "@playwright/test";
import { hasCreds, SKIP_REASON } from "./helpers";

// These tests exercise the login page itself, so they must start from a
// clean (unauthenticated) context rather than the pre-authenticated
// storageState the rest of the suite uses.
test.use({ storageState: { cookies: [], origins: [] } });

test.describe("auth", () => {
  test.skip(!hasCreds, SKIP_REASON);

  test("valid login lands on /dashboard", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("you@company.com.my").fill(process.env.E2E_EMAIL!);
    await page.getByPlaceholder("••••••••").fill(process.env.E2E_PASSWORD!);
    await page.getByRole("button", { name: "Sign in" }).click();

    await page.waitForURL("**/dashboard", { timeout: 30_000 });
    await expect(page).toHaveURL(/\/dashboard/);
  });

  test("bad credentials shows the inline error, no crash", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("you@company.com.my").fill(process.env.E2E_EMAIL!);
    await page.getByPlaceholder("••••••••").fill("definitely-the-wrong-password");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByText(/Supabase auth failed/i)).toBeVisible({ timeout: 15_000 });
    await expect(page).toHaveURL(/\/login/);
  });
});
