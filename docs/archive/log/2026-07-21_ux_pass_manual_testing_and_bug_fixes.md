# 2026-07-21 — Manual/automated feature testing of the UX pass, two real bugs found and fixed

**Branch:** `mvp3-prod`
**Commits:** `75a2aca` (hydration fix, from the tail end of 07-20), `0e61ee1` (race-condition fix), `5341206` (E2E suite hardening)

---

## Context

User hit a real hydration error on the login page from yesterday's UX pass (screenshot: `error-at-login-page.png`) and asked for it fixed, then for a proper server check and feature-by-feature test. Later, after reviewing the results, asked to fix a race-condition finding and continue.

Both servers had gone down overnight (environment reset) — restarted cleanly, no lingering issues.

## Bug 1 — ToastProvider hydration mismatch (already committed at the end of 07-20, `75a2aca`)

`typeof document !== "undefined"` gated the toast portal — `false` on the server, `true` immediately on the client's first (pre-hydration) render pass, so React discarded and regenerated the tree on every page load. Fixed with the standard mounted-flag-in-`useEffect` pattern. Verified with a real headless-Chromium check (curl can't catch client-side hydration mismatches) across `/login`, `/signup`, `/documents`, `/dashboard` — zero errors, 4 repeated checks.

## Thorough feature walkthrough

Used Playwright with the E2E test account to actually click through nearly every page changed in the UX pass — not just assertions, real screenshots reviewed visually. Confirmed working correctly: image preview (the original complaint's root cause — purely the hydration error blocking the view, the feature itself was always fine), toasts (including multiple stacked at once), danger-styled confirm dialogs, Escape/backdrop-click modal closing, skeletons, empty states, trash flow, bulk tag. Found and cleaned up 3 stray test documents left in the tenant from an interrupted run (including a manual upload of the error screenshot itself).

## Bug 2 — stale-poll race could resurrect a just-deleted document row (`0e61ee1`)

**The real bug.** `documents/page.tsx` polls every 3s while any document has a non-terminal status. If that poll's request was already in flight when a single-doc action (trash/restore/permanent-delete) applied its own optimistic `setData`, the poll's now-stale response could resolve afterward and silently overwrite the optimistic update — reintroducing a row the user had just deleted. The underlying delete always succeeded server-side (confirmed via backend logs + reload) — this was UI-only staleness, not data loss, but still a real, confusing bug.

Fixed with a generation counter (`dataGenerationRef`) bumped by every fetch — initial load, poll tick, and each optimistic mutation (trash/restore/permanent-delete). A response only applies if the counter hasn't moved since that request started, so any poll response that predates a mutation gets ignored regardless of arrival order.

Verified with a dedicated Playwright repro that deliberately times a permanent-delete to land inside an in-flight poll window (the exact sequence that broke before the fix) — 3/3 clean runs, row removed and never reappears.

## Bug 3 (test infrastructure, not product) — E2E suite flakiness under repeated runs (`5341206`)

Stress-testing Bug 2's fix by running the full suite repeatedly surfaced two real bugs in the E2E harness itself:

1. `helpers.ts::permanentlyDeleteByFilename` hunted for a specific row in the Trash view, racing against that view's own post-navigation fetch. Switched to "trash the doc, then Empty Trash" — safe because every spec runs against a dedicated throwaway tenant with nothing else to protect, and it removes the race entirely instead of adding more waits around it. Along the way, also caught a `Locator.isEnabled()` one-shot-check bug (waits for the element to attach, not for `disabled` to actually clear) — needed `expect(locator).toBeEnabled()`, the real poll-until-true assertion. The exact same class of mistake as the original helper bug from 07-20's session, caught again by testing thoroughly rather than assuming a "fix" was correct.
2. `playwright.config.ts` had no global `expect()` timeout override, silently falling back to Playwright's 5s default — too tight for a dev environment that already logs "Slow filesystem detected" and can take 20–30s to cold-compile a route on its first hit in a run. Set `expect: { timeout: 15_000 }`.

Also root-caused, while chasing an apparent "document vanished after upload" mystery, that the real explanation was **dedup working as designed** — sha256 dedup keys off checksum regardless of `deleted_at`, so a trashed-but-not-permanently-deleted document silently blocks re-uploading the same file bytes. This was already documented in the helper's own docstring from yesterday; today's investigation just confirmed it empirically after a long diagnostic chase (several dead-end hypotheses: StrictMode double-fetch races, backend commit-timing, frontend rendering bugs — all ruled out with direct API/network inspection before landing on the real cause).

**Verification:** 3 consecutive full-suite runs (15 test executions) on a pre-cleaned tenant, all green — versus 2 of the prior 3 runs failing before this fix.

## Overall

- `tsc --noEmit` / `eslint`: clean throughout every fix today — same 26-problem baseline, zero new issues (confirmed via the same stash-and-diff methodology as 07-20 where needed).
- `pytest`: not re-run — zero backend files touched by any fix today.
- Tenant left in a fully clean state (verified: 0 active docs, 0 trashed docs, 0 custom fields, only the 4 legitimate onboarding-kit starter tags).

## Visual testing pass (post-fix, on demand)

User asked directly "can you do the visual testing?" — re-ran a fresh Playwright walkthrough on the current (post-fix) code and reviewed screenshots directly rather than trusting only DOM-level assertions, since today's whole investigation started from an automated-checks-passed-but-real-bug-present situation.

12 screenshots reviewed: clean login page, empty-state Documents, table/grid loading skeletons (first attempt accidentally captured `AuthProvider`'s own session-check spinner from a full `page.reload()`, not the component's own `TableRowsSkeleton` — re-tested correctly by triggering a client-side sort change instead, which is the actual code path the skeleton covers), the image preview that was the origin of the whole bug report, the share modal + its toast, the "Empty trash?" danger dialog, the migrated Tags modal (Escape-closes confirmed), the bulk-select toolbar, and the "Move to trash?" bulk danger dialog + its success toast (the exact flow behind Bug 2's fix, confirmed visually holding up).

One non-bug learned along the way: single-row trash (the row's own trash icon) has no confirmation dialog by design — it's reversible, only bulk-trash/permanent-delete warrant a confirm. Tenant cleaned up after.

## Known-issues audit (not yet acted on)

User asked "what issues might still be there" — answered from a position of having just spent a full day finding bugs automated checks missed, so erred toward flagging real gaps rather than declaring victory:

- **The same race-condition pattern (poll + optimistic `setDoc`, no generation guard) almost certainly exists on `documents/[id]/page.tsx`** — confirmed via grep: a `setInterval` poll identical in shape to the one fixed in `documents/page.tsx`, plus 10+ separate handlers calling `setDoc(...)` directly (trash, restore, save metadata, tag assign/unassign, custom-field value set/clear, extraction correction save, share create/revoke). Not fixed, not tested today.
- **The IDP worker has not run at all this session** — confirmed via `Get-CimInstance Win32_Process`: only the backend API server process exists, no worker. Every test document created today sat at `status=queued` forever. OCR, text extraction, thumbnailing, and the deterministic-extraction/VLM-fallback pipeline are entirely unverified against today's changes.
- Untested surface area: `/search` page, Dashboard, Saved Views, Correspondents, Settings' Security/API Keys/Notifications tabs, the document detail page's Metadata/Extraction-correction/Raw-JSON/History tabs, real Supabase team-invite email flow, MyInvois/UBL ingestion. Only 4 E2E specs exist total (auth, upload, documents-filter, bulk-ops) — correspondents, custom-fields CRUD, saved views, export file content, and the public shares page have zero automated coverage.
- Pre-existing and not concerning: 2 unrelated TS errors in `search/page.tsx`, `sentry_sdk` missing from the local venv (local-only test failure), the Windows RQ scheduler gap for stuck job retries (documented, production runs on Linux).

## Next

Still not pushed to `origin/mvp3-prod` — 9 commits now sitting locally since `2990bc3`. Recommend pushing now given the depth of verification today (both the manual/visual walkthrough and the now-3x-stable E2E suite). Before further feature work: fix the detail-page race condition (same pattern, same fix, already understood) and do a real worker-processing pass (start the worker, let a document actually complete, verify the UI holds up through a real status transition) — both flagged above, neither started.
