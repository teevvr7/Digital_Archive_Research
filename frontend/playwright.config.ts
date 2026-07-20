import { defineConfig, devices } from "@playwright/test";
import { hasCreds } from "./e2e/helpers";
import { STORAGE_STATE_PATH } from "./e2e/global.setup";

const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  // Specs share one live test tenant (uploads, tags, trash) — run serially
  // so one spec's writes can't race another's reads.
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  globalSetup: hasCreds ? "./e2e/global.setup.ts" : undefined,
  use: {
    baseURL,
    storageState: hasCreds ? STORAGE_STATE_PATH : undefined,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: baseURL,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
