import { chromium, type FullConfig } from "@playwright/test";
import path from "path";
import { hasCreds } from "./helpers";

export const STORAGE_STATE_PATH = path.join(__dirname, ".auth", "user.json");

/** Logs in once through the real login page and saves the session so every
 * spec starts already authenticated, instead of re-logging in per test. */
export default async function globalSetup(config: FullConfig) {
  if (!hasCreds) return;

  const baseURL =
    config.projects[0]?.use?.baseURL ?? process.env.E2E_BASE_URL ?? "http://localhost:3000";
  const browser = await chromium.launch();
  const page = await browser.newPage();

  await page.goto(`${baseURL}/login`);
  await page.getByPlaceholder("you@company.com.my").fill(process.env.E2E_EMAIL!);
  await page.getByPlaceholder("••••••••").fill(process.env.E2E_PASSWORD!);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(`${baseURL}/dashboard`, { timeout: 30_000 });

  await page.context().storageState({ path: STORAGE_STATE_PATH });
  await browser.close();
}
