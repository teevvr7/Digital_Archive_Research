# Manual Feature Test Pass — All Services Live (IDP Excluded)
**Date:** 2026-07-06
**Branch:** `mvp-lvl2` (at `9914b2b`, no code changes made during this session — pure testing)
**Scope:** Walk every non-IDP feature end-to-end via the real UI with backend + worker + frontend running live against Supabase. Structured/VLM extraction quality is explicitly out of scope for this pass.

---

## Services started

| Service | Command | Port | Result |
|---|---|---|---|
| Backend API | `venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` | 8000 | ✅ up, `/api/docs` responds |
| Worker | `venv/Scripts/python.exe -m app.worker` | — | ✅ SimpleWorker listening on `idp` queue |
| Frontend | `npm run dev` (Next.js) | 3000 | ✅ up |

Redis was already running locally (port 6379) from a prior session — not started fresh.

---

## Steps completed

### 1. Auth (signup/login/bootstrap) — ✅ PASS
Logged in with an existing account. Bootstrap/session flow worked, landed on Dashboard automatically.

### 2. Dashboard + storage meter — ✅ PASS
- Stat widgets present: total documents, processed, queued for processing, need attention.
- Storage Usage card (0%, 132 KB / 10.0 GB) matches the sidebar storage widget exactly — no drift between the two.
- Browser console clean (only Next.js Fast Refresh/HMR noise, "No Issues").

### 3. Upload — multi-format ingestion — ✅ PASS (with one known-good IDP fallback observed)
Uploaded 6 files: `Datawiz AI Marketing.pdf`, `DAMS - Ain.xlsx`, `SevenMayParse_Technical_Architecture.pdf`, `big-invoice.pdf` (dup), `100-charles.pdf`, `Candidate Suitability Review- sample.docx`.

- **Dedup confirmed:** `big-invoice.pdf` correctly skipped as "already archived" (sha256 match against an existing doc) — not re-processed.
- All 5 new files transitioned `queued → completed` (or `needs_review`) individually, worker log confirms per-file parser routing:
  - PDF w/ text layer → PyMuPDF, no OCR (`Datawiz AI Marketing.pdf`, `100-charles.pdf`)
  - PDF w/o text layer → RapidOCR fallback, 11 pages (`SevenMayParse_Technical_Architecture.pdf`)
  - `.xlsx` → office_parsing extractor
  - `.docx` → office_parsing extractor
- **`SevenMayParse_Technical_Architecture.pdf` → `needs_review`:** deterministic gate scored 0.74 (just under the 0.75 threshold), VLM fallback then failed with `httpx.ReadError` / `openai.APIConnectionError` (Lightning AI GPU endpoint unreachable — expected, it's a demo placeholder that spins down). **This is correct behavior, not a bug** — pipeline did not block, worker moved on and processed the next queued job normally. Confirms the "never blocks on the LLM" reliability rule holds under a real failure.
- No worker crashes across any of the 5 jobs.

### 4. Documents list — table/grid + thumbnails — ✅ PASS
- Table view: icons, type, status, date, size, actions all populated correctly.
- Grid/card view: PDF thumbnails render as real page-preview images (per user confirmation).
- Switching back to table view still works.

### 5. Document detail — viewer, download, edit metadata — ✅ PASS (functionally), 🐛 1 bug found
- PDF viewer renders inline correctly.
- Download opens in a new tab, downloads fine from there.
- **Title edit:** changed `100-charles.pdf`'s title to `100-charles-testing.pdf` — saved correctly, confirmed in the detail page's Metadata panel (`Title: 100-charles-testing.pdf` vs. immutable `Original filename: 100-charles.pdf`, both shown distinctly, exactly as designed).
- **Document type edit:** changed type via dropdown (e.g. Invoice → Receipt) — saved correctly, reflected everywhere including the list's Type column.
- **🐛 Bug found:** the title edit does **not** show up in the main Documents list. Root-caused live: `frontend/app/(app)/documents/page.tsx` lines 145, 147, 898 all render `doc.originalFilename` for the "Document" column (table AND card view), never `doc.title`. The API/DB side is correct; only the list display is wrong. See `project_critical_findings.md` #11 in Claude memory.

---

## Bugs found this session (all deliberately deferred, not fixed yet)

1. **`document_date` heuristic produces nonsensical dates.** Two docs got `1949-07-06` and `3844-07-06`/`3844-07-03` as their document date — the `dateparser` heuristic picked up garbage from document text/OCR output instead of a real date. Needs root-cause: inspect the actual source text/OCR output that produced these values.
2. **Document-date range filter (`date_from`/`date_to`) not working properly**, per user report. Not yet diagnosed — could be the bad dates above making it *look* broken, could be a real query/frontend wiring bug independent of #1. Needs separate verification once #1 is fixed.
3. **Documents list shows `originalFilename` instead of `title`.** Editing a document's title (Phase 5 correction UI) has no visible effect in the primary list view (table or card), silently defeating the feature. Fix: swap to `doc.title` (fallback to `originalFilename` if empty) at all three call sites in `documents/page.tsx`; also check `documents/[id]/page.tsx` for the same pattern.

All three logged in Claude's persistent memory (`project_critical_findings.md` #10, #11) for follow-up in a dedicated bug-fix session — user explicitly asked to queue them rather than fix opportunistically mid-test.

---

## Infra note: all 3 services crashed mid-session, restarted cleanly

Partway through Step 6 (Tags), all three background processes (backend, worker, frontend) died within moments of each other:
- Backend: `Segmentation fault` in `venv/Scripts/python.exe -m uvicorn ...`
- Frontend: `Segmentation fault` in the `npm`/`node` process
- Worker: exit code 127

All three dying simultaneously with unrelated crash signatures (segfault in two independent processes + exit 127 in a third) points to the underlying shell/session host being reset (e.g. terminal/session interruption), not an application bug — no corresponding error in Supabase, no OOM evidence, no shared code path between a Python segfault and a Node segfault. Restarted all three cleanly; backend/worker/frontend all came back up with no state loss (Postgres/Redis/Storage are all external to these processes).

---

## Step 6 — Tags (in progress)

Tag creation works. **Bug found + FIXED live (user asked to fix immediately since it blocked further tag testing):**

4. **`POST /documents/{doc_id}/tags/{tag_id}` (assign tag) crashed the frontend with `Failed to execute 'json' on 'Response': Unexpected end of JSON input`.** Root cause: the backend correctly returns `204 No Content` (`backend/app/modules/tags/router.py:48-55`), but `frontend/lib/api.ts`'s generic `post<T>()` helper unconditionally called `res.json()` with no empty-body handling — the same bug class `delete_()` already had fixed in Phase 6, just never applied to `post()`. The backend assignment itself almost certainly succeeded; only the client-side response parsing crashed afterward.
   - **Fix applied:** `post<T>()` in `lib/api.ts` now checks `res.status === 204` and returns `undefined` (mirrors `delete_()`), same as the existing pattern for empty-body responses.
   - Verified: `npx tsc --noEmit` clean except the 2 pre-existing unrelated errors in `search/page.tsx` (present before this change, per Phase 6 notes). **Re-verified live by user in the browser — tag assign now succeeds with no error banner.**
   - Checked for the same latent bug elsewhere: grepped all backend `status_code=status.HTTP_204_NO_CONTENT` routes — every other 204 route is a `DELETE` (already handled by the fixed `delete_()`). Tag assign is the only `POST` route returning 204, so this was an isolated fix, not a wider sweep.

5. **Minor UI polish flagged, not fixed:** the tag-add control on the document detail page is "so small" per user — queued as a cosmetic follow-up, not addressed in this session.

6. **`unassign_tag` is not idempotent — rapid double-click on remove throws a 404.** `backend/app/modules/tags/service.py:110-121` raises `HTTPException(404, "Tag is not assigned to this document.")` if the `DocumentTag` row is already gone, unlike `assign_tag` (same file, line 92-107) which uses `.on_conflict_do_nothing()` and is idempotent. A rapid double-click fires two DELETE requests; the first succeeds, the second 404s and surfaces as an error banner in the UI. **Not fixed — queued.** Single-click remove and tag-filter on the Documents list both confirmed working correctly by user.

**Tags (Step 6) — CLOSED.** Create ✅, assign ✅ (after fix), unassign ✅ (minor double-click edge case queued above), filter ✅.

---

## Infra note: all 3 services crashed a second time, restarted cleanly

Same segfault/exit-139 pattern as before (backend + frontend segfault, worker crash) hit again while starting Step 7, right around the day rollover (2026-07-06 → 2026-07-07). Same conclusion as before: not an app bug (unrelated crash signatures across independent processes), more likely the host machine idling/sleeping. Restarted all three; no state loss.

## Step 7 — Correspondents: missing manual-assign feature found + built

CRUD works. But assigning a correspondent to a specific document was **not possible at all** — not a bug, a real feature gap. Root-caused in code (not guessed):
- `backend/app/modules/files/schemas.py::DocumentPatchIn` only supported `title`, `document_type`, `document_date`, `extracted_data_patch` — no `correspondent_id` field, and no dedicated `POST /documents/{id}/correspondent` endpoint (unlike tags, which got one).
- `frontend/app/(app)/documents/[id]/page.tsx:941` just rendered `doc.correspondent?.name ?? "—"` as a static read-only row — no edit control existed because there was nothing to call.
- Correspondents could only ever get attached via the Phase 4 auto-matching engine (content-pattern rules run once during pipeline processing), never manually afterward.

**User chose to build the feature now** rather than defer it. Implemented:
- Backend: added `correspondent_id: uuid.UUID | None` to `DocumentPatchIn`; `patch_document` (`files/service.py`) validates the correspondent exists (tenant-scoped via RLS) before setting it, 404s if not, allows `null` to clear — same pattern as the existing `document_date` clear-on-null handling.
- Frontend: `DocumentPatch` type gained `correspondentId`; detail page now fetches `apiCorrespondents()` on load, edit-mode gained a **Correspondent** `<select>` (with a "— None —" clear option) wired through the existing `editDraft`/`handleSave` flow — reuses the same PATCH endpoint and edit-mode UI already used for title/type/date, not a new sub-resource endpoint like tags.
- Verified: `npx tsc --noEmit` clean (same 2 pre-existing unrelated `search/page.tsx` errors only), `pytest` 212/212 still passing, both services confirmed live after restart. **Re-verified live by user in the browser — Correspondent dropdown appears in edit mode and saves correctly.**

## Infra note: corrupted Turbopack dev cache after the repeated restarts

Opening a document threw a Next.js runtime error: `Jest worker encountered 2 child process exceptions, exceeding retry limit`, with a "(stale)" badge on the Next.js version indicator. Root cause: likely two `next dev` processes briefly wrote to the same `.next/` cache concurrently during the earlier crash/restart cycles, corrupting Turbopack's incremental cache. Also found 4 orphaned `node` processes surviving from ~90 minutes earlier (start times ~1:07–1:09 PM) that the "killed"/"segfault" notifications never actually reaped — explains why frontend kept responding through those "failures."

**Fix:** force-killed all `node` processes, deleted `frontend/.next` (build cache, safe to regenerate), restarted `npm run dev` clean as the sole instance. First compile per route was slow afterward (cold Turbopack cache + this project's filesystem is flagged "slow" by Next.js itself — 36s for the first `/documents/[id]` load), but subsequent loads are normal speed. No source code was touched by this cleanup.

---

**Correspondents (Step 7) — CLOSED.** CRUD ✅, manual assign ✅ (feature built this session), filter ✅.

## Step 8 — Custom Fields — ✅ PASS

Created a custom field, set its value on a document, reloaded the page — value persisted correctly. No issues found.

---

## Real-world usage — what each feature is actually for

The technical pass/fail notes above confirm the plumbing works. This section is the "why would a business actually use this" view — how each feature maps to a real archive/document-management workflow, not just a checkbox.

- **Auth (signup/login/bootstrap).** Every company using this archive gets its own isolated tenant the moment an admin signs up — no manual provisioning. This is what lets the product be sold to multiple companies off one deployment without them ever seeing each other's documents (enforced at the database level via RLS, not just app code).

- **Dashboard + storage meter.** The first thing an office manager or admin checks each morning: how many documents came in overnight, how many are still processing, how many failed and need a human look, and — critically for a cost-conscious free-tier deployment — how close the tenant is to its storage cap before uploads start getting rejected.

- **Upload (multi-format ingestion).** The front door. A real business doesn't only get clean PDFs — they get scanned paper invoices, Excel expense sheets, Word contracts, emailed receipts. This is what lets someone drag in a shoebox's worth of mixed files and have every single one land in the archive safely, with duplicates silently caught (so re-uploading the same invoice twice by accident doesn't create clutter or double-count storage).

- **Documents list (table/grid + thumbnails).** The daily browsing view — like Windows Explorer or Google Drive for this company's documents. Grid view with thumbnails is for someone visually scanning "which invoice was that one" without opening each file; table view is for someone scanning status/date/size at a glance across many documents at once.

- **Document detail (viewer, download, edit metadata).** Where someone actually does their job: opening an invoice to check a figure without downloading it first (inline viewer), pulling the original file for an accountant (download), or fixing a wrong title/date/type after the system auto-extracted something imperfectly (edit) — this is the human-in-the-loop correction step that keeps the archive accurate over time.

- **Tags.** Freeform organization on top of whatever structure the system already imposes — e.g. tagging documents "Urgent", "Q3-Audit", or "Client-ABC" so they surface together regardless of type or sender. The auto-match rules mean a business can set up "any invoice from this vendor gets tagged X" once and never touch it again.

- **Correspondents.** Answers "show me everything from/to this person or company" — e.g. every document ever received from a specific supplier or client, across invoices, contracts, and emails alike. The manual-assign feature built today matters because auto-matching won't always get it right (a supplier's name might vary across documents), so a human needs to be able to correct or assign it after the fact.

- **Custom fields.** Lets each business bolt on the specific data fields *they* care about that the system doesn't know about out of the box — a "PO Number", an internal "Cost Center" code, a "Contract Expiry" date — without needing a schema change or a developer. This is what makes the archive adaptable per-customer instead of one-size-fits-all.

- **Search.** The headline feature of the whole product (per the project's own north star) — "if a user can't find a file in seconds, nothing else matters." Fuzzy filename match covers "I remember it was called something like *invioce_2026*" typos; full-text content search covers "I don't remember the filename at all, but I know it mentioned Nestlé condensed milk" — letting someone find a document by what's *inside* it, not just what it's named. The dedicated Search page's highlighted snippet is what lets a user confirm at a glance "yes, this is the right document" without opening every result.

- **Trash.** The safety net for the delete button — accidentally removing an important invoice shouldn't mean it's gone forever. This is what lets someone undo a mistake, or a business enforce a retention/cleanup policy (empty trash after N days) without permanent data loss being one misclick away. Trashed documents needing to stay out of search results is just as important as restore working — otherwise "deleted" documents would keep cluttering the one thing the whole product is built around (findability).

---

## Step 9 — Search: found + fixed a critical regression (search was 100% broken, not just fuzzy match)

Typing an exact, correctly-spelled word ("Datawiz") into the Documents search bar returned **"Failed to fetch"** and no results. Root-caused with direct DB queries (not guessed):

- Backend log showed `sqlalchemy.exc.ProgrammingError: function word_similarity(character varying, text) does not exist` on every search request — a hard 500, not a frontend issue.
- Diagnostic queries against the live Supabase DB (as the app's actual `app_user` connection) confirmed: `SHOW search_path` → `"$user", public` (no `extensions` schema); `pg_trgm`/`word_similarity` lives in the `extensions` schema (Supabase convention); `app_user` **does** have `USAGE` on `extensions` (so not a grants problem) — purely an unqualified-function-name resolution gap.
- `backend/app/modules/search/query.py` lines 70 and 76 called `func.word_similarity(...)` unqualified. Since the search SQL combines the FTS clause and the fuzzy-match clause in **one** `WHERE`/`ORDER BY`, the whole query died regardless of whether the FTS half alone would have matched — explaining why even an exact-word search failed, not just typo/fuzzy searches.

**This is a real regression, not a latent bug**: search had 29 passing tests and was verified working back in Milestone D (2026-06-10/11), when the app connected as the Postgres `postgres` superuser. It silently broke the moment Phase 0's RLS hardening (`digital_ui/log` critical finding #1) switched the live connection to the narrower `app_user` role — nobody updated the search code for the new role's `search_path`. **It was never caught by `pytest`** because the test suite's DB fixture apparently resolves `word_similarity` fine (different connection/role than the live app) — a real blind spot in test coverage worth remembering: passing tests didn't mean the live app's actual connection matched.

**Fix (user chose the code-only option over altering the DB role):** qualified both call sites to `func.extensions.word_similarity(...)` in `search/query.py`. No DB/role/RLS changes. Verified: raw SQL query against live Supabase confirms the qualified call now returns a real similarity score; `pytest app/tests/test_search_service.py` (6/6) and full suite (212/212) still pass; fix is live via uvicorn `--reload`, pending final live-browser retry from user.

**Retest after the fix:** `--reload` had logged "Reloading..." for `search/query.py` but the worker process never actually restarted (same PID served requests before and after) — same class of issue as the earlier orphaned-frontend-process incident, WatchFiles/uvicorn reload not fully trustworthy after this many restart cycles. Force-killed the stale backend PID (left the worker process untouched) and started a genuinely fresh one. Confirmed via a brand-new PID in the startup log.

User retested live: exact-word search now returns fast, correct results. Fuzzy filename match also confirmed working. Also clarified an app design point while testing: there are **two separate search surfaces** — the Documents list's inline search bar (filter/rank only, no snippet — never built there) vs. the dedicated `/search` page (fetches a `ts_headline` snippet with `<mark>` highlights, shown only when the match came from document content rather than just the filename). Initial "snippet not showing" report was from the Documents list page (expected, not a bug); confirmed working correctly on the dedicated Search page.

**Search (Step 9) — CLOSED.** Critical regression found + fixed ✅, FTS ✅, fuzzy filename ✅, snippet highlighting (dedicated Search page) ✅, fast (<2s target met, felt near-instant) ✅.

## Step 10 — Saved Views — ✅ PASS

Created a saved view with a filter combination, cleared filters, reapplied the saved view via the sidebar/pill bar — filter combination re-applied correctly. No issues found.

- **Real-world usage:** lets an office manager set up "Needs Review invoices from Q3" or "All completed receipts this month" once and revisit it with one click, instead of re-entering the same filter combination every day — the saved-view-as-dashboard-widget pattern this borrows from paperless-ngx.

---

## Step 11 — Bulk Operations: found + fixed a stale-list bug

All three bulk actions (assign tag, set type, trash) work correctly server-side — user confirmed each mutation actually applied. But the Documents list **never visually updated afterward** — required a manual page refresh every time to see the result.

Root-caused in code (not guessed): `frontend/app/(app)/documents/page.tsx` lines 361, 374, 387 (the three bulk handlers) all called `setPage((p) => p)` after their mutation, with a comment claiming it would "trigger re-fetch via dep change." It doesn't — React bails out of re-running an effect when a state setter receives a value that's unchanged (`p => p` is always a no-op for a primitive), so the `useEffect` that actually fetches the document list (depends on `page` among other filters, lines 248-256) never re-fired. The mutation succeeded; the UI just never asked for fresh data.

**Fix:** extracted the effect's fetch body into a plain `refreshDocuments()` function (called by the effect on filter/page changes, same as before) and had all three bulk handlers call `refreshDocuments()` directly instead of the fake `setPage` trick. Minimal, no new abstractions, matches the existing plain-function style already used for `buildQuery()`. Verified: `npx tsc --noEmit` clean (same 2 pre-existing unrelated `search/page.tsx` errors only) — frontend-only change, no backend touched, no need to re-run pytest. **Re-verified live by user in the browser — list now updates immediately after all three bulk actions.**

- **Real-world usage:** bulk ops are for the "I just uploaded 50 scanned invoices from one vendor, tag all of them at once" scenario, or year-end cleanup ("select everything older than X, trash it"). A stale list after a bulk action would make a user think the action silently failed and possibly retry it — the fix prevents that false signal.

**Bulk Operations (Step 11) — CLOSED.** Assign tag ✅, set type ✅, trash ✅ — all three confirmed working end-to-end after the stale-list fix.

---

## Step 12 — Trash: found + fixed a real gap (trashed docs were still searchable)

Trash/restore itself works correctly: trashed docs appear in the Trash view, restore brings them back to the main list. But user found trashed documents were **excluded from the Documents-list inline search, yet still fully findable on the dedicated Search page** — an inconsistency between the two search surfaces.

Root-caused in code (not guessed): `backend/app/modules/search/service.py::search_documents` built its query as `select(...).where(or_(content, fname))` — **no `deleted_at` filter at all**. Compare `files/service.py::list_documents`, which explicitly does `Document.deleted_at.is_(None)` (or `.is_not(None)` for the trash view). The dedicated search module was built in Milestone D, before soft-delete/trash existed (added later in Phase 3) — nobody went back to add the exclusion when trash shipped. This defeats the purpose of trash as a soft-hide mechanism (still recoverable, but shouldn't be freely discoverable) for one of the app's two search paths.

**Fix:** added `Document.deleted_at.is_(None)` to the `where(...)` clause in `search_documents`, matching the pattern already used in `list_documents`. Verified: full `pytest` suite still 212/212 (no existing test caught this gap either — same test-coverage blind spot pattern as the `word_similarity` regression). Given `--reload` proved unreliable earlier this session (silently served stale code twice), force-killed the backend cleanly and started a genuinely fresh process rather than trust hot-reload. **Re-verified live by user in the browser — trashed docs confirmed excluded from the dedicated Search page.**

**Trash (Step 12) — CLOSED.** Soft-delete ✅, restore ✅, search-leak bug found + fixed ✅.

---

## ALL 12 STEPS COMPLETE

Full feature-test pass finished. Summary of what was found and fixed this session, beyond the walkthrough itself:

**Fixed live:**
1. Tag-assign crashed on 204 No Content (`post<T>()` missing empty-body handling) — `frontend/lib/api.ts`
2. Correspondent manual-assign was entirely missing (feature gap, not a bug) — built `correspondent_id` support end-to-end
3. Search was 100% broken — `word_similarity` unqualified against `app_user`'s `search_path` (Phase 0 role regression) — `backend/app/modules/search/query.py`
4. Bulk ops never refreshed the list — `setPage((p) => p)` no-op — `frontend/app/(app)/documents/page.tsx`
5. Trashed documents were still fully searchable via the dedicated Search page — missing `deleted_at` filter — `backend/app/modules/search/service.py`

**Queued for later (not fixed, deliberately deferred):**
- `document_date` heuristic produces nonsensical dates (1949, 3844) on some docs
- Document-date range filter reported not working properly
- Documents list displays `originalFilename` instead of `title` (edits invisible in list)
- `unassign_tag` not idempotent — rapid double-click 404s
- Tag-add control on document detail page is too small (cosmetic)
- A separate untracked `logs/` folder duplicates the tracked `log/` convention (repo hygiene, not urgent)

All backend fixes verified against the full `pytest` suite (212/212 throughout, no regressions); all frontend fixes verified with `tsc --noEmit` (clean except 2 pre-existing unrelated errors in `search/page.tsx`, present before this session). IDP/structured-extraction quality was explicitly out of scope for this pass per the user's request.

---

## 2026-07-07 — Follow-up pass: all 6 queued items fixed

User asked to go back and fix everything queued above. Done, in order:

### 1. Documents list showing `originalFilename` instead of `title` — FIXED
Swapped `doc.originalFilename` → `doc.title || doc.originalFilename` at `frontend/app/(app)/documents/page.tsx` (table view line ~147, card view line ~902) and `frontend/app/(app)/search/page.tsx` (line ~313, same bug on the Search page results list — found while fixing this, not originally flagged). `documents/[id]/page.tsx` already did this correctly (breadcrumb line 427); its other `originalFilename` uses (image `alt`, download tooltip, the "Original filename" metadata row) are intentional, left untouched.

### 2. `unassign_tag` not idempotent — FIXED
`backend/app/modules/tags/service.py::unassign_tag` now returns silently instead of raising 404 when the `DocumentTag` row is already gone — mirrors `assign_tag`'s `on_conflict_do_nothing` idempotency. Updated the existing test (`test_tags.py`) that asserted the old 404 behavior to assert the new no-op instead, since that was a real behavior change, not just an addition.

### 3. Tag-add control too small — FIXED (cosmetic)
`documents/[id]/page.tsx` tags footer (chips, "Add" button, its dropdown): bumped `text-xs`→`text-sm`, tightened padding (`py-0.5`→`py-1`, dropdown `py-1.5`→`py-2`), icons up one size step (`w-2.5`→`w-3`, `w-3`→`w-3.5`). Applied consistently across the whole control group, not just the button, so chips and "Add" don't end up visually mismatched.

### 4. Stray untracked `logs/` folder — FIXED
Moved the 3 remaining files (`2026-06-29_phase4_tags_correspondents.md`, `2026-06-30_bootstrap_rls_fix.md`, `2026-06-30_worker_matching_fix.md`) into the tracked `log/` folder (no filename collisions), removed the now-empty `logs/` directory. Confirmed via `git status` — all 4 files (these 3 + this session's own log) now show as untracked additions under `log/`, ready to commit whenever the user chooses; nothing lost.

### 5. `document_date` heuristic producing nonsense dates — ROOT-CAUSED + FIXED
Root cause found in `backend/app/modules/idp/jobs.py::_guess_document_date`: it free-mines the first 2000 characters of extracted text via `dateparser.search.search_dates` with **no plausibility check** on the result. Pulled the actual live documents' real `extracted_text` via a direct DB query (not guessed) to confirm the exact trigger:
- `big-invoice.pdf`'s address line **"VIC, TRARALGON, 3844, AUSTRALIA"** — dateparser misread the Australian postcode as a year → `document_date=3844-07-03` / `3844-06-30` on two separate uploads of the same content.
- `Datawiz AI Marketing.pdf` (a marketing pitch deck with no genuine document date anywhere) → `document_date=1949-07-06`, dateparser finding *something* implausible in free text that had nothing date-like in it at all.

**Fix:** added a plausibility bound to `_guess_document_date` — reject (return `None` instead) anything more than 3 days in the future or more than 50 years in the past. Verified directly against the real extracted text of all 3 affected documents (queried live): all 3 now correctly return `None` instead of the old garbage values. Added 2 regression tests (`test_universal_ingestion.py`) — these mock `dateparser.search.search_dates`'s return value directly (with the exact real bad values, 3844-07-03 and 1949-07-06) rather than trying to reproduce dateparser's exact fuzzy text-matching with synthetic text, since two earlier attempts at synthetic repro text both failed to trigger the same misparse dateparser's version-specific fuzzy logic did — the guard being tested is the plausibility bound, not dateparser's internals. Full suite: 214/214 passing.

**Existing bad data:** the 3 already-corrupted rows in the live DB don't get touched by a code fix alone. Per user's explicit choice, ran a one-time `UPDATE documents SET document_date = NULL WHERE id = ANY(...)` targeted at the exact 3 known-bad document IDs (not a broad date-range match) — confirmed 3 rows updated, verified by returning clause.

### 6. Document-date range filter "not working properly" — ROOT-CAUSED + FIXED
Root cause: **not a query bug** — `Document.document_date >= date_from` / `<= date_to` is correct SQL. The real issue is data sparsity: queried the live DB directly and found only 2 of 15 documents had a genuinely correct `document_date` (the rest were either the 3 corrupted rows above, or — the bulk of them, 11 of 15 — simply `NULL`, since most uploaded file types never get a detected date). Since `NULL >= x` is never true in SQL, **any** date-range filter silently excluded the majority of the archive — not broken, just confusingly sparse.

User's direction: show `uploaded_at` as a fallback wherever `document_date` is missing, both in the list display and (for consistency, so filtering matches what's shown) in the filter query itself.
- **Frontend:** `documents/page.tsx` table view's date column now always shows a second line — `doc.documentDate || doc.uploadedAt.split("T")[0]` — instead of only showing it when `document_date` happened to exist.
- **Backend:** `files/service.py::list_documents` now filters on `func.coalesce(Document.document_date, func.cast(Document.uploaded_at, Date))` instead of `Document.document_date` directly, so undated documents are filtered by when they entered the archive instead of silently vanishing from every date-range query.
- Verified: full `pytest` suite 214/214, `tsc --noEmit` clean (same 2 pre-existing errors only).

**All 6 queued items closed.** Backend restarted cleanly after each change (force-kill + fresh process, not relying on `--reload`, per the lesson learned earlier this session). Pending final live-browser confirmation from user on items 1, 3, 5, 6 (items 2 and 4 are pure repo/cosmetic, no behavior to re-verify).

---

## 2026-07-08 — Live verification round: found + fixed one more real bug (title search gap)

Verifying item 1 (title display), user confirmed the Documents list and Search page both correctly show `title` now — **but** searching for a word that's only in the new title ("test"/"testing", part of `100-charles-testing.pdf`) found nothing.

Root-caused with two direct code checks, not guessed:
- `search_tsv` (the full-text index) is built **exactly once**, at initial pipeline processing (`idp/jobs.py`), from `original_filename + extracted_text` — **never `title`**, and **`patch_document` never rebuilds it** when the title changes via the correction UI.
- `filename_match` (the fuzzy/typo tier, `search/query.py`) only ever compared against `Document.original_filename`, never `title`.

Net effect: renaming a document (the entire point of the correction UI) makes the new name permanently unsearchable on both search tiers, while the stale original filename remains searchable forever. Given the product's own stated north star is "retrieval is the headline feature," this was worth fixing immediately rather than queuing — user agreed.

**Fix (touches 3 files):**
- New shared helper `build_search_text(title, original_filename, extracted_text)` in `search/query.py`, used by both the pipeline and the patch endpoint so they can never drift out of sync again.
- `idp/jobs.py::process_document` now builds `search_tsv` via `build_search_text(doc.title, ...)` instead of skipping title.
- `files/service.py::patch_document` now rebuilds `search_tsv` whenever `title` changes (previously never touched it at all).
- `search/query.py::filename_match`/`rank_expr` now take `func.greatest()` of word_similarity against **both** `coalesce(title, original_filename)` and `original_filename` directly — so a renamed doc is findable by *either* its new title *or* its old filename, not one at the expense of the other.

**Test-writing note worth remembering:** the first fixture pick for a new regression test (`test_search_service.py`, a doc renamed from `"Old Scan 001.pdf"` to `"Renamed Budget Report.pdf"`) accidentally broke two unrelated pre-existing tests — turned out `word_similarity('schedule', 'old scan 001.pdf') = 0.222`, just over the 0.2 fuzzy-match threshold, a pure trigram coincidence unrelated to the fix itself. Diagnosed by directly querying `word_similarity` for candidate strings against every existing query term in the file before picking a collision-free one (`"Bluefox Import 2024.pdf"`). Lesson: when adding a new seeded doc to a shared search-test fixture, check it doesn't accidentally fuzzy-match the other tests' query terms — pg_trgm collisions are non-obvious and won't be caught by eyeballing the strings.

**Existing data backfill:** per user's choice, ran a one-time backfill re-deriving `search_tsv` for all 17 live documents via the same `build_search_text` logic (code fix alone only applies to new uploads/renames going forward, not already-processed documents) — confirmed 17 rows updated.

Verified: full `pytest` suite 216/216 (214 + 2 new regression tests: renamed-title findable by new name, and still findable by old filename). Backend **and** worker both restarted fresh (this fix touches `idp/jobs.py`, which the worker imports, unlike prior fixes this session that only needed the API restarted). **Re-verified live by user — title search confirmed working, both new and old names.**

**Verification round continued:** `document_date` fix confirmed (Datawiz AI Marketing.pdf / big-invoice.pdf show sensible dates now) and date-range filter confirmed (previously-undated docs now show up). User's follow-up feedback: the fallback logic (show `document_date` when present, else `uploaded_at`) was more complexity than needed — simpler and more predictable to just always show/filter by `uploaded_at` in the Documents list, dropping `document_date` from the list column and the date-range filter entirely (uploaded_at is never null, so no fallback logic needed at all).

**Simplification applied:**
- `documents/page.tsx` date column: now unconditionally `doc.uploadedAt.split("T")[0]`, no more `documentDate ||` fallback.
- `files/service.py::list_documents`: `date_from`/`date_to` now filter on `cast(Document.uploaded_at, Date)` directly, dropped the `coalesce(document_date, uploaded_at)` — since `uploaded_at` is never null, this is strictly simpler and always reliable, no NULL-exclusion edge case possible.
- `document_date` (the extracted content date, when detected) is untouched everywhere else — still shown in the document detail page's Metadata tab, still stored, still what `_guess_document_date`'s plausibility guard protects; it's just no longer used for the list column or the date-range filter.
- Verified: `pytest` 216/216, `tsc --noEmit` clean (same 2 pre-existing errors only). Backend restarted fresh (API-only change, worker left running untouched this time).

---

## Trash page: 2 more real bugs found + fixed

While verifying, user noticed the Trash view was missing a per-file delete, and the storage meter never reacted to deletions. Both root-caused in code, not guessed:

**Bug 1 — no per-file permanent delete.** `backend/app/modules/files/router.py` only ever exposed `POST /documents/empty-trash` (bulk, deletes *everything*). No endpoint existed to permanently delete one selected trashed document, and the frontend's trash-row actions only ever rendered a "Restore" button — no delete control at all.

**Bug 2 — storage meter never updates.** `files/service.py::empty_trash` deleted the storage objects and DB rows but **never decremented `Tenant.storage_used_bytes`** — compare the upload path, which explicitly increments it. A real accounting leak: the meter only ever grew, even after permanently deleting everything, which would eventually cause false "storage full" upload rejections.

**Fix (both, same session):**
- New `ACT_PERMANENT_DELETE` activity type (backend `models/activity_event.py` + frontend `types/index.ts`, kept in sync per the existing "must match frontend exactly" convention).
- New `permanent_delete_document(db, user, doc_id)` service function (`files/service.py`) — 404 if not found, 409 if not already trashed (permanent delete only reachable from the trash view, mirrors the soft-delete-first safety net), deletes storage objects, hard-deletes the row, decrements `storage_used_bytes` by the doc's `size_bytes` (floored at 0 via `func.greatest(...)` as a defensive guard).
- `empty_trash` fixed the same way — now sums freed bytes across all deleted docs and decrements once.
- New `DELETE /documents/{id}/permanent` endpoint (`router.py`), `apiPermanentDelete` client function (`lib/api.ts`).
- Frontend: trash-view row actions now show **both** Restore and a "Delete permanently" button (previously Restore only), with a confirm dialog.
- **Also fixed while touching this code:** `handleEmptyTrash` had the *exact same* stale-list bug already fixed once this session for bulk ops — it called `setData(null); setPage(1)`, a no-op when already on page 1 (React skips re-running the fetch effect when a setter receives an unchanged value). Switched to the existing `refreshDocuments()` helper instead.

Added 8 new tests (`test_file_management.py`): 404/409/storage-delete/db-delete/activity-event/storage-decrement coverage for the new function, plus storage-decrement regression tests for `empty_trash`. Verified: full `pytest` suite 224/224, `tsc --noEmit` clean (same 2 pre-existing errors only). Backend restarted fresh. **Re-verified live by user — trash-page permanent delete confirmed working.**

## Infra note: uvicorn `--reload` served genuinely stale code, then port 8000 got stuck on an unkillable phantom process

While verifying the permanent-delete fix, the user hit `DELETE /documents/{id}/permanent → 404 {"detail":"Not Found"}` — FastAPI's generic "no route matched" body, not the custom 404 raised by the handler. Root-caused conclusively (not guessed): the route was 100% present and correctly registered in the source (verified by directly importing `app.modules.files.router` in a fresh one-off script and listing its routes) — but the *running* uvicorn process didn't have it. `--reload`/WatchFiles had silently kept serving an old app instance despite logging "Reloading..." and "Application startup complete" with no visible errors, for at least the second time this session. The prior verification method (checking `/api/docs` returns 200) was insufficient — that only proves *an* app booted, not that *this specific* route loaded; the real test is comparing a known-good route's auth-rejection status (401) against the new route's status through an unauthenticated request.

Attempting a clean restart then hit a second, unrelated problem: port 8000 became occupied by a process (`PID 32640`) that `netstat` reported as `LISTENING` but neither PowerShell's `Stop-Process` nor `taskkill` could find in the process table at all — consistent with a WSL2/Docker Desktop network-namespace artifact (the frontend log had shown a `172.17.0.1` Docker bridge address earlier in the session). This was outside what's fixable from the sandboxed shell; user resolved it on their end (likely a machine restart — post-fix, the frontend's network address changed from the Docker bridge IP to a real LAN IP, and all prior orphaned processes were gone).

**Decision: dropped `--reload` entirely for the rest of the session**, running backend as a single stable process (`uvicorn app.main:app --host 0.0.0.0 --port 8000`, no `--reload`) to eliminate this whole class of silent-stale-code bug. Trade-off: every future backend code change now needs an explicit manual restart (already the established practice this session anyway, given `--reload`'s unreliability), but no more silent staleness.

**New verification standard going forward:** after any backend restart, don't just check `/api/docs` responds — hit the *specific* new/changed route unauthenticated and confirm it returns 401 (route matched, auth rejected) rather than 404 (route missing). This is now the reliable way to confirm a route actually loaded.

---

## 2 more real bugs found + fixed: storage meter desync + Dashboard title display

**Bug 3 — sidebar storage meter desyncs from the Dashboard's storage widget.** Root-caused: **two independent data sources** for the same `tenants.storage_used_bytes` value. The sidebar reads `useAuth().tenant.storageUsedBytes` (populated via `apiMe()`, only refreshed when `useAuth().refresh()` is explicitly called — `upload/page.tsx` already does this after a byte-storing upload, per the 2026-07-03 fix). The Dashboard fetches its own fresh copy via `apiDashboard()` on mount, completely independent of the sidebar's cached value. The new trash-page mutations (`handlePermanentDelete`, `handleEmptyTrash`) — the two that actually free real storage — never called `refresh()`, so the sidebar kept showing a stale number while the Dashboard (fetching fresh on each visit) showed the correct one, appearing "not synced."

**Fix:** `documents/page.tsx` now calls `useAuth().refresh()` after both `handlePermanentDelete` and `handleEmptyTrash` (not after trash/restore, which don't change storage — soft-delete doesn't free bytes). Same established pattern as the upload-page fix, just never extended to the trash page when it was built.

**Bug 4 — Dashboard's Recent Documents widget showed `originalFilename` instead of `title`.** Same bug class already fixed twice this session (Documents list, Search results) — this third occurrence on the Dashboard page was simply missed earlier. Fixed the same way: `doc.title || doc.originalFilename`.

Both frontend-only changes. Verified: `tsc --noEmit` clean (same 2 pre-existing errors only). No backend restart needed; frontend hot-reloads. **Re-verified live by user — storage meter now stays in sync, Dashboard shows renamed titles.**

---

## Session status: all reported issues resolved

Every bug found during this feature-test pass and its follow-up verification rounds is now fixed and confirmed live: the original 5 (tag-assign 204, correspondent-assign built, search regression, bulk-ops stale list, trash-search leak), the 6 queued items (title display, tag idempotency, tag sizing, log folder, document_date heuristic, date filter), the title-search gap (search_tsv/filename_match never included title), and the trash-page pair (missing per-file delete + storage-meter desync, plus the Dashboard title-display miss caught in the same pass). 224/224 backend tests passing throughout, `tsc --noEmit` clean. Backend now runs without `--reload` for reliability (see the infra note above) — remember to manually restart it after any future backend change in this project.
