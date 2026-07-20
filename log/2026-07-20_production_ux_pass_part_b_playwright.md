# 2026-07-20 — Production-Feel UX Pass, Part B (Playwright E2E smoke suite)

**Branch:** `mvp3-prod`
**Commits:** `fed2f62` (Part A — UX primitives), `75a2aca` (hydration fix), `6ab3065` (this entry — Playwright suite)

---

## Context

Continuation of the same day's UX pass (see `2026-07-20_production_ux_pass_part_a.md`). After Part A shipped, the user hit a real hydration error on the login page (`c:\Users\teeva\Downloads\error-at-login-page.png`) — `ToastProvider`'s portal rendered based on `typeof document !== "undefined"`, which is `false` on the server and `true` on the client's very first pass, so React discarded and regenerated the tree on every load. Fixed with the standard mounted-flag-in-`useEffect` pattern (commit `75a2aca`).

User then created a dedicated E2E test account (`e2e-test@datawiz.test`, its own isolated tenant via the app's own signup flow — auto-confirms server-side, no Supabase dashboard needed) and asked to continue with Part B.

## What shipped

**Harness** (`frontend/e2e/`, `frontend/playwright.config.ts`):
- Installed `@playwright/test` + Chromium locally.
- `global.setup.ts` logs in once through the real login page, saves `storageState` so every spec starts authenticated; specs needing a clean unauthenticated context (`auth.spec.ts`) override it per-file.
- Env-gated: the whole suite skips (not fails) when `E2E_EMAIL`/`E2E_PASSWORD` are unset — verified both ways (ran once with them set, once without).
- `webServer` reuses an already-running dev server rather than starting a duplicate.
- Specs run serially (`workers: 1`) — they share one live test tenant and would race each other's writes otherwise.

**Specs:**
- `auth.spec.ts` — valid login → `/dashboard`; bad credentials → inline error, no crash.
- `upload.spec.ts` — a fixture PDF (generated via PyMuPDF, real extractable text, not a renamed blank file) shows up in the Documents list after upload.
- `documents-filter.spec.ts` — the full real journey behind the type-gated custom-field filter (07-16 work): create a custom field on `/custom-fields` → predefine it for Invoices → upload an invoice with a value for that field → on `/documents`, confirm the picker only unlocks once Type=Invoice is selected → Contains-mode substring match narrows correctly (a non-matching value returns zero results) → switching to a type with no predefined fields (Receipt, on this fresh tenant) hides the picker again.
- `bulk-ops.spec.ts` — bulk tag assignment fires a success toast; bulk trash opens the new danger-styled confirm dialog and, on confirm, fires a success toast and removes the row.

**A real bug caught while writing these:** `getByLabel("Email address")` on the login page hung for the full 30s timeout — the page's `<label>` and `<input>` are plain siblings with no `htmlFor`/`id` link, so there's no accessible-label association for Playwright (or a screen reader) to find. Switched specs to `getByPlaceholder` rather than touching production markup, since fixing the label association wasn't in scope for this pass.

**Idempotency (the trickiest part):** the app's dedup constraint is keyed on `(tenant_id, sha256)` regardless of `deleted_at` — a trashed document still blocks re-uploading the same bytes. Discovered this would silently break `documents-filter.spec.ts` on a second run (the newly-created custom field would end up with zero values attached, since a deduped "upload" never creates a document row, so `_apply_upload_time_fields` never runs). Fixed by having every spec that uploads a fixture **permanently delete** it afterward (`helpers.ts::permanentlyDeleteByFilename` — trash, switch to Trash view, delete permanently, confirm) rather than just trashing it. `documents-filter.spec.ts` also deletes its throwaway custom field; `bulk-ops.spec.ts` deletes its throwaway tag. Verified by running the full suite twice back-to-back with zero failures.

**data-testid hooks added** (small, targeted, matching Part A's convention): `custom-fields/page.tsx` — `new-field-name`, `new-field-type`, `predefined-picker-{type}`, `predefined-confirm-{type}`, `predefined-add-open-{type}`, `predefined-card-{type}`. `CustomFieldInput` gained an optional `testId` prop, wired through the upload popup's predefined-field inputs as `predefined-field-input-{fieldName}`.

**Also fixed:** the hydration fix's `useEffect(() => setMounted(true), [])` tripped the same `react-hooks/set-state-in-effect` rule Part A's log already flagged as a pre-existing baseline noise-maker — but this occurrence is the actual point of the pattern (defer the portal to strictly after hydration), not an oversight. Added a one-line `eslint-disable-next-line` with the reasoning inline, keeping the lint baseline at exactly 26 problems instead of 27.

## Verification

- `npx playwright test` with `E2E_EMAIL`/`E2E_PASSWORD` set: **5/5 passed**, twice in a row (idempotency check).
- `npx playwright test` with them unset: **5/5 skipped**, exit 0, no error.
- `tsc --noEmit`: clean — same 2 pre-existing `search/page.tsx` errors.
- `eslint`: 26 problems (20 errors, 6 warnings) — identical to the established baseline, zero new issues.
- `pytest`: not re-run — zero backend files touched in either Part A or Part B.

## Next

Not yet pushed to `origin/mvp3-prod` — the user is testing Part A's UX manually first before deciding when to push. `npm run test:e2e` / `npm run test:e2e:ui` are the scripts going forward; a throwaway Supabase test tenant now exists for this purpose (`e2e-test@datawiz.test`) and should be reused, not recreated, for future E2E work. CI wiring for this suite is explicitly out of scope for this pass (local-run only, per the approved plan).
