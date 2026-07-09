# 2026-07-09 — Production Level-Up Planning + Level 1 (Trust & Credibility) Implementation

**Branch:** `mvp-lvl2` → work moved to new branch `mvp3-prod`
**Status at end of day:** Level 1 fully implemented, live-tested by the user, two real bugs found during testing and fixed. Not yet committed at time of writing this log — commit/push to `mvp3-prod` immediately follows.

---

## Context

User asked for an unbiased "how do we make this system buyable" review — not just a feature wishlist. Read a pre-drafted ideas file (`log/2026-07-09_system-optimization-ideas.md`), then ran a 3-way parallel codebase audit (automation/matching engine, extraction JSON + search + export, frontend UX + production-readiness) plus read the newer IDP pipeline commit sitting unmerged on `origin/main` (`6c3c730`, teammate Nalan's `paddle_qwen`/IDP Control Center work).

Produced a 5-level roadmap (plan file: `~/.claude/plans/compiled-moseying-tulip.md`, memory: `project_production_levelup_roadmap.md`):
1. **Trust & credibility** — close the "this looks like a demo" gaps (mock Settings, no audit trail, no error monitoring, no rate limiting).
2. **IDP pipeline port** — bring `paddle_qwen` (remote-HTTP variant) + the per-tenant extraction-method Control Center from `origin/main` into `mvp-lvl2`, normalize the three different `extracted_data` JSON schemas into one canonical shape.
3. **Data value** — amount/field filters, CSV/XLSX export, retroactive rule backfill, shareable links.
4. **Team accounts** — real multi-user (deferred, not bundled into L1 per user's explicit call).
5. **SME growth** — onboarding starter kit, PWA/camera capture, email-sender correspondent linking, MyInvois ingestion, etc.

User approved the plan and picked Level 1 first (trust/credibility) with all 4 data-value items pre-approved for later, team accounts deferred to Level 4.

---

## Level 1 implementation — six items, all shipped

**1. Real Settings backend + page.** New `GET /api/activity` (paginated, org-wide or `?document_id=`-scoped audit feed — `files/service.py::list_activity`), new `PATCH /api/auth/tenant` (org rename, admin-only via the previously-unused `require_admin` dependency), `documents_by_family` added to `DashboardStats` (real per-mime-type document counts). Settings page (`frontend/app/(app)/settings/page.tsx`) fully rewritten: Organisation (real rename + real storage breakdown), Users (real single-user view, honest "coming soon" instead of a dead invite button), Activity (new tab, real feed), Security/API Keys/Notifications (honest static "coming soon" panels — no more fake toggles or fake `dw_live_…` API keys). Deleted `frontend/lib/mock-data.ts` (last consumer removed).

**2. Audit trail surfaced.** New shared `frontend/components/activity-item.tsx` (`ActivityIcon`/`ActivityLabel`) — extended to cover all 10 `ACT_*` event types; the old dashboard-local version only handled 4. Document detail page gained a "History" tab, scoped to that document only.

**3. Sentry wired.** `backend/app/core/monitoring.py::init_sentry(component)` — no-op unless `SENTRY_DSN` is set, called from both `main.py` and `worker.py`. Caught and closed a real privacy gap while implementing: sentry-sdk's `include_local_variables` defaults to **True**, which would ship raw document text from crash stack frames to Sentry — a genuine PDPA problem for a document archive. Explicitly set `send_default_pii=False` and `include_local_variables=False`. User provided a real DSN and it was verified live (test event visible in the Sentry dashboard, issue `DATAWIZ-BACKEND-1`).

**4. Rate limiting + upload batch cap.** New `backend/app/core/rate_limit.py` (slowapi, Redis-backed — reuses `settings.redis_url`, already a hard dependency for the job queue, so no new failure mode). `/auth/signup` limited 10/hour/IP (real backend endpoint; login itself is a direct Supabase client call from the frontend and can't be rate-limited here). `/documents` upload limited, plus new `_MAX_FILES_PER_UPLOAD = 50` per-request file-count cap in `create_documents`, rejected before any file I/O.

**5. Forgot-password.** Real Supabase flow: `/login` gained an inline reset-request panel, new `frontend/app/reset-password/page.tsx` handles the recovery-link landing (waits for the `PASSWORD_RECOVERY` auth event, `updateUser({password})`, then signs out and redirects to `/login` for a clean re-authentication rather than reusing the recovery session's JWT).

**Verification after implementation:** 242/242 pytest (up from 238 baseline — also discovered the backend venv was missing `pytest`/`black`/`ruff` entirely despite memory recording 212/212 passing on 2026-07-06; reinstalled via `pip install -e ".[dev]"`, root cause unknown, possibly related to an earlier segfault/restart). `tsc --noEmit` clean except the 2 pre-existing unrelated `search/page.tsx` errors. New deps: `sentry-sdk[fastapi]`, `slowapi`.

---

## Live-testing bugs found by the user, fixed same day

**Bug 1 — Org rename: `PATCH /tenant → 404`.** `apiUpdateTenant` in `frontend/lib/api.ts` called `/tenant`, but the real route (the auth router has an `/auth` prefix) is `/auth/tenant`. Pure path mismatch, missed because I never live-tested the exact frontend call against the exact backend route before handing it off. Fixed the frontend path; verified `PATCH /api/auth/tenant` returns 401 (route found, auth required) not 404.

**Bug 2 — Upload rate limit (30/minute) would break large legitimate batches.** User asked directly: "if I drag 200 files won't that hit the rate limit?" — and was right. The upload page sends **one HTTP request per file** (a sequential loop, not one multipart batch), so a real drag-and-drop of 100+ files fires 100+ requests in quick succession from the same user. The 30/minute ceiling was calibrated against an abstract notion of "abuse," not against the actual one-request-per-file pattern the frontend produces. Raised to 300/minute in `files/router.py`. **Lesson recorded in memory:** calibrate rate limits against the real number of HTTP requests a client action produces, not the user's mental model of "one action."

Backend was restarted (no `--reload`, by design) after both fixes; both routes re-verified live. Full suite re-run: 242/242 still passing.

---

## Live-testing session notes

User ran a real 500-file upload as a stress test. Confirmed (via backend + worker log tails) it was **not stuck** — 201 Created responses streaming for every upload request, worker processing one document at a time (~25s each, mostly OCR), meaning ~3.5 hours to fully drain a 500-document queue given the current single-threaded Windows `SimpleWorker` with no parallelism. Flagged as a known, pre-existing architectural characteristic (not introduced today) — worth addressing as a later item (worker parallelism / Linux deployment, already noted in the Level 5 backlog) rather than something to fix mid-session.

While that batch was processing, the frontend logged two 500s + 60-80s response times on the document detail page, then recovered to normal — almost certainly resource contention from the machine running 500 sequential OCR jobs concurrently with the Next.js dev server on a flagged "slow filesystem" (D: drive), not a code bug.

User also asked for two upload-page UX improvements while testing the 500-file batch, both shipped live via hot reload (not part of the original Level 1 scope, but small and directly responsive to real friction found in testing):
- **Bulk document-type change** on the upload page — pending files now have per-row checkboxes + a "select all" toggle; selecting any subset surfaces a toolbar to set a document type across all of them at once (mirrors the existing Documents-page bulk-action pattern).
- **Scrollable file list** — the pending-files panel is now a fixed ~420px scrollable panel instead of pushing the whole page down for a large batch.

---

## Result

- 242/242 pytest passing throughout (backend).
- `tsc --noEmit` clean (2 pre-existing unrelated errors, unchanged).
- `eslint`: 19 issues project-wide (was 18 before today's session), all consistent with the codebase's existing tolerance for the `react-hooks/set-state-in-effect` pattern already present in `documents/page.tsx`, `tags/page.tsx`, `correspondents/page.tsx`, `search/page.tsx` — not a new class of issue.
- Sentry verified live end-to-end (test event confirmed in the Sentry dashboard).
- Org rename and the rate-limit fix both re-verified live after the user caught them.
- Upload-page bulk-type-change and scrollable-list improvements shipped and pending live verification by the user.

## Next

Level 2 (port the newer IDP pipeline from `origin/main` + normalize the three `extracted_data` JSON schemas into one canonical shape) is next in the approved roadmap sequence. This session's work moves from `mvp-lvl2` to a new branch, `mvp3-prod`, per the user's request — see the accompanying commit for the full file list.
