# 2026-07-01 — Phase 6 Complete + System Startup & Testing

**Branch:** `main`  
**Status at end of day:** Phase 6 fully complete ✅ — 212/212 tests, all services running, ready for manual smoke test

---

## Phase 6 summary (Retrieval & UX)

Phase 6 was completed in this session. All items below were built and verified.

### Backend additions

| Item | Detail |
|---|---|
| Migration `0011_saved_views` | `saved_views` table — JSONB `filter_state`, `is_default`, standard NULLIF-GUC RLS + `authenticated` grants |
| `modules/views/` | Full CRUD service + router: `GET/POST/PATCH/DELETE /api/saved-views` |
| `list_documents` extended | New filter params: `correspondent_id`, `date_from`, `date_to`, `inbox` (inbox uses subquery to avoid JOIN conflict with tag filter) |
| Bulk operations | `POST /documents/bulk-trash` — soft-delete + ActivityEvent per doc |
| | `POST /documents/bulk-tag` — assign or remove a tag across N docs; assign uses `pg_insert().on_conflict_do_nothing()` for idempotency |
| | `POST /documents/bulk-set-type` — `UPDATE documents SET document_type = ?` via `update().where(id.in_(...))` |
| Tests | 14 new in `test_saved_views.py` + 13 new in `test_bulk_ops.py` = 27 new tests |

**Total: 212/212 tests passing.**

### Frontend additions

| Item | Detail |
|---|---|
| `lib/api.ts` | Added saved-view API (`apiSavedViews`, `apiCreateSavedView`, `apiPatchSavedView`, `apiDeleteSavedView`), bulk-op API (`apiBulkTrash`, `apiBulkTag`, `apiBulkSetType`), extended `DocumentsQuery` with 4 new filter params |
| `documents/page.tsx` | Full rewrite: grid/table toggle, thumbnail cards (`ThumbnailImage` lazy-loads signed URL), correspondent dropdown filter, date-from/to range, inbox toggle, multi-select + bulk action bar, saved-views pill bar, "Save current view" inline form |
| `views/page.tsx` | New page — saved views CRUD management table with filter summary label + "Open view" link |
| `components/sidebar.tsx` | Added "Inbox" quick-link (NAV_ITEMS) and "Saved Views" under Organize section |
| `types/index.ts` | Added `SavedView` interface |

### Bug fixed during Phase 6

**`delete_<T>` 204 response crash** — the existing generic `delete_` fetch helper in `lib/api.ts` called `res.json()` on all responses, including `204 No Content`. This threw `SyntaxError: Unexpected end of JSON input` on every delete (tags, correspondents, custom fields, saved views). Fixed by checking `res.status === 204` first and returning early before attempting JSON parse.

**`StatusBadge` className prop** — `DocCard` in the grid view passed a `className` prop to `<StatusBadge>`, but the component only accepts `{ status: ProcessingStatus }`. Fixed by wrapping it in a `<div className="...">` instead.

**`TestCreateSavedView` mock DB failures** — 4 create tests failed because `SavedView.id` and `SavedView.created_at` are `None` after `db.flush()` on a MagicMock DB (server defaults don't execute). Fixed by patching `app.modules.views.service._to_out` in those tests — same pattern used in `test_custom_fields.py`.

---

## System startup issues encountered today

### 1. `uvicorn` not on system PATH

**Symptom:** `Start-Process powershell -Command "uvicorn ..."` opened a window that immediately failed silently.

**Root cause:** `uvicorn` is installed as a Python package but its script isn't registered on the Windows PATH. `where.exe uvicorn` returned nothing.

**Fix:** Use `python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload` instead. Confirmed working via `python -m uvicorn --version` → `Running uvicorn 0.38.0`.

---

### 2. Redis not installed natively on Windows

**Symptom:** `redis-server` not found on PATH; WSL only has the `docker-desktop` distro (no bash, no Redis).

**Root cause:** Redis is not natively installed. The only WSL distro is the Docker Desktop backend (`docker-desktop`), which has no user shell.

**Fix:** Redis was already running from a previous session as `backend-redis-1` Docker container on port 6379. Verified with `docker exec backend-redis-1 redis-cli ping` → `PONG`. No action needed — just use the existing container.

---

### 3. Next.js returning 404 on all routes

**Symptom:** Frontend process (PID 39048) was listening on port 3000 but every route (`/`, `/login`, `/_next/static`) returned HTTP 404.

**Root cause:** The `Start-Job` approach used to capture Next.js startup output killed the process after the job ended. The node process still showed as listening but was in a broken state. Additionally, checking via `Invoke-WebRequest -MaximumRedirection 5` with `UseBasicParsing` gave misleading error messages.

**Fix:** 
1. Killed the stale process (`Stop-Process -Id 39048`)
2. Restarted via `Start-Process powershell -ArgumentList '-NoExit', '-Command', 'npm run dev'` (persistent window, not a background job)
3. Verified with raw `.NET WebRequest` instead of `Invoke-WebRequest` — returned `200 OK`

---

## End state

| Service | Status |
|---|---|
| Redis | Running in Docker (`backend-redis-1`, port 6379) ✅ |
| Backend | `python -m uvicorn`, port 8001, `HTTP 403` on auth-required routes ✅ |
| IDP Worker | `python -m app.worker`, connected to Redis queue ✅ |
| Frontend | Next.js 16.2.7 (Turbopack), port 3000, `HTTP 200` ✅ |

- **Tests:** 212/212 passing
- **Migration:** `0011_saved_views` applied and live (alembic at head)
- **Phase 6:** Complete ✅

## Next

Manual smoke test — upload files, test search/filters, saved views, bulk operations, tags, correspondents. No new phase started yet.
