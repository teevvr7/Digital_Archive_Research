# 2026-07-08 — Trash Permanent-Delete, Title-Search Gap, Storage Meter Desync

**Branch:** `mvp-lvl2`
**Status at end of day:** All issues found today fixed and verified live. Committed as `71ef998`, pushed to `origin/mvp-lvl2`.

---

## Context

Continuation of the 2026-07-06 full feature-test pass (see `log/2026-07-06_feature_test_pass.md` for the complete walkthrough and the first two rounds of fixes). Today was a live verification pass over yesterday's fixes, which surfaced four new real bugs and one infra reliability problem.

---

## Bug 1 — Renamed documents were permanently unsearchable by their new title

Verifying the "documents list shows title, not filename" fix from yesterday, searching for a word only in a document's *new* title (after renaming it via the correction UI) returned nothing on the dedicated Search page.

**Root cause:** `search_tsv` (the full-text index) is built exactly once, at initial pipeline processing (`idp/jobs.py`), from `original_filename + extracted_text` — never `title`. `patch_document` never rebuilt it on rename either. `filename_match` (the fuzzy/typo tier) also only ever compared against `original_filename`. Renaming a document — the entire point of the correction UI — made the new name permanently unsearchable on both tiers, while the stale original filename stayed searchable forever.

**Fix:** new shared `build_search_text(title, original_filename, extracted_text)` helper (`search/query.py`), used by both `idp/jobs.py` (initial processing) and `patch_document` (now rebuilds `search_tsv` on title change — previously never touched it). `filename_match`/`rank_expr` now take `func.greatest()` of similarity against both title and original filename, so a renamed doc is findable by either name. Backfilled `search_tsv` for all 17 existing live documents.

Two new regression tests in `test_search_service.py` — mocking `dateparser`-style exact inputs wasn't relevant here, but worth noting: the first fixture pick (a doc renamed `"Old Scan 001.pdf"` → `"Renamed Budget Report.pdf"`) accidentally broke two unrelated pre-existing tests, because `word_similarity('schedule', 'old scan 001.pdf') = 0.222`, just over the 0.2 fuzzy-match threshold — a pure trigram coincidence. Diagnosed by directly querying `word_similarity` for candidates against every existing query term in the file before picking a collision-free one.

## Bug 2 — Trash page: no per-file permanent delete

Only `POST /documents/empty-trash` existed (bulk, deletes everything). No way to permanently delete a single selected trashed document — the frontend trash-row actions only ever rendered "Restore".

**Fix:** new `permanent_delete_document()` service function (404 if not found, 409 if not already trashed — mirrors the soft-delete-first safety net), `DELETE /documents/{id}/permanent` endpoint, and a "Delete permanently" button next to Restore in the trash row actions.

## Bug 3 — Storage meter never reacted to deletions

`empty_trash` deleted storage objects and DB rows but never decremented `Tenant.storage_used_bytes` — the upload path increments it, nothing ever decremented it. The meter only ever grew, even after permanently deleting everything.

**Fix:** both `permanent_delete_document` and `empty_trash` now decrement `storage_used_bytes` by the freed bytes (floored at 0).

## Bug 4 — Sidebar storage meter desynced from the Dashboard's storage widget

After fixing Bug 3, the sidebar and Dashboard showed *different* storage numbers from each other.

**Root cause:** two independent data sources for the same value. The sidebar reads `useAuth().tenant.storageUsedBytes` (from `apiMe()`, only refreshed via an explicit `refresh()` call — `upload/page.tsx` already calls it after upload). The Dashboard fetches its own fresh copy via `apiDashboard()` on every mount. The new trash-page mutations never called `refresh()`, so the sidebar went stale while the Dashboard stayed correct.

**Fix:** `documents/page.tsx` now calls `useAuth().refresh()` after `handlePermanentDelete` and `handleEmptyTrash` (not trash/restore, which don't change storage).

## Bug 5 — Dashboard's Recent Documents widget showed the raw filename, not the title

Same bug class fixed twice yesterday (Documents list, Search results) — a third occurrence on the Dashboard page, simply missed. Fixed the same way: `doc.title || doc.originalFilename`.

## Also fixed in passing

`handleEmptyTrash` had the exact same stale-list bug already fixed once yesterday for bulk ops — it called `setData(null); setPage(1)`, a no-op when already on page 1 (React skips re-running an effect when a setter receives an unchanged value). Switched to the existing `refreshDocuments()` helper.

---

## Infra: `uvicorn --reload` served genuinely stale code, then port 8000 got stuck

Verifying the permanent-delete endpoint, got `DELETE /documents/{id}/permanent → 404 {"detail":"Not Found"}` — FastAPI's generic "no route matched" body, not the custom 404 the handler raises. Root-caused conclusively: the route was 100% correct in source (confirmed by directly importing `app.modules.files.router` in a fresh one-off script and listing its routes), but the running uvicorn process didn't have it, despite logging "Reloading..." and "Application startup complete" with no errors. Checking `/api/docs` returns 200 after a restart proved insufficient — that only confirms *an* app booted, not that *this* route loaded.

Attempting a clean restart then hit a second, unrelated problem: port 8000 became occupied by a process `netstat` reported as `LISTENING` but neither PowerShell's `Stop-Process` nor `taskkill` could find in the process table at all — consistent with a WSL2/Docker Desktop network-namespace artifact (the frontend log had shown a `172.17.0.1` Docker bridge address earlier). Not fixable from the sandboxed shell; the user resolved it on their end (likely a machine restart — afterward the frontend's network address changed to a real LAN IP, and all prior orphaned processes were gone).

**Decisions:**
- Dropped `--reload` entirely for the rest of the session — backend now runs as a single stable process (`uvicorn app.main:app --host 0.0.0.0 --port 8000`, no `--reload`). Trade-off: every future backend change needs an explicit manual restart, but eliminates this whole bug class.
- **New verification standard:** after any backend restart, hit the specific new/changed route unauthenticated and confirm 401 (route matched, auth rejected) rather than 404 (route missing), comparing against a known-good sibling route — not just that `/api/docs` responds.

---

## Result

- Full `pytest` suite: **224/224** (216 prior + 8 new: 2 title-search regression tests in `test_search_service.py`, 6 permanent-delete/storage-decrement tests in `test_file_management.py`).
- `tsc --noEmit`: clean (same 2 pre-existing unrelated errors in `search/page.tsx`, present since before this work started).
- All 5 bugs re-verified live in the browser by the user.
- Along the way, caught and restored an unrelated log file (`2026-07-01_phase6_complete_system_startup.md`) that had gone nearly empty in the working tree before it could get swept into a commit by accident — restored from HEAD, no data lost, not part of the final commit.
- Committed as `71ef998` ("fix: title search index gap, trash permanent-delete + storage accounting, storage meter desync"), pushed to `origin/mvp-lvl2`.

## Final verification sweep

Two fixes from yesterday's "queued items" round (`unassign_tag` idempotency on rapid double-click, tag-control sizing) had been fixed but never explicitly re-tested live. Confirmed today — both work correctly, no issues. **Every bug found across the full 2026-07-06 → 2026-07-08 feature-test pass and its follow-up rounds is now fixed and confirmed live.** Nothing outstanding from this pass.
