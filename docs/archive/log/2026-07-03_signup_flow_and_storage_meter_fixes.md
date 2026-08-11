# 2026-07-03 — Signup Flow End-to-End Fix + Sidebar Storage Meter Fix

**Branch:** `mvp-lvl2`
**Status at end of day:** Signup works end-to-end; sidebar storage meter now refreshes after upload. Verified via curl (backend) + hot-reload (frontend).

---

## Problem 1 — Sign-up was completely broken

**Symptoms reported by user:**
1. "The page stays on *rendering* after clicking Sign up" (spinner never resolves).
2. "A lot of red-line errors pop up after clicking Create account."

Five independent root causes were found and fixed — all five were needed for signup to work end-to-end.

### 1a. Signup endpoint read a non-existent settings field (HTTP 500)

**Root cause:** `app/modules/auth/router.py::signup()` read `settings.supabase_service_key`, which does not exist on the config (`AttributeError` → 500).

**Fix:** Corrected to `settings.supabase_service_role_key`. Also hardened the endpoint:
- Added `Authorization: Bearer <service_role_key>` header (Supabase admin API needs both `apikey` and `Authorization`).
- Wrapped the call in `httpx.AsyncClient(timeout=15.0)` + `RequestError` handling → returns `502` instead of hanging.
- Parse Supabase's error body and surface its `msg`/`error_description`/`message` instead of a raw dump.

### 1b. Frontend called a relative URL → hit the Next server, got 404 HTML

**Root cause:** The signup page did `fetch("/api/auth/signup")` (relative), which hit the Next.js dev server (no such route) and dumped a 404 HTML page into the error box — the "red-line errors."

**Fix in `frontend/lib/api.ts`:** Added `apiSignup(email, password)` that POSTs to the absolute `${BASE}/auth/signup` (no auth header — the user has no session yet) and cleanly extracts the `detail` field on error.

### 1c. Frontend/backend port mismatch (8001 vs 8000)

**Root cause:** A previous session temporarily moved uvicorn to 8001; the frontend `.env.local` / `api.ts` fallback still pointed at a dead 8001 while uvicorn ran on 8000.

**Fix:** Aligned everything on **8000** — `frontend/.env.local` (`NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api`), `api.ts` fallback, and `start-system.ps1`.

### 1d. "Page stuck rendering" — Next 16 Suspense requirement

**Root cause:** `login/page.tsx` used `useSearchParams()` without a `<Suspense>` boundary. Next 16 de-opts the whole route to client rendering (and errors in build) when this isn't wrapped — the visible symptom was the page never resolving.

**Fix:** Renamed `LoginPage` → `LoginForm` and wrapped it in `<Suspense fallback={null}>` inside a new default-export `LoginPage`.

### 1e. First-login token lacks `tenant_id` → bootstrap 500 + duplicate tenant

**Root cause (two-part):**
- On first login the Supabase access token has **no `app_metadata.tenant_id`**. `bootstrap()` created the tenant and did `db.flush()` **before** setting the RLS GUC — the `tenants` RLS `WITH CHECK (id = app.current_tenant)` rejected the insert (the `uuid_pk` column default only materializes at flush). Result: 500 "new row violates row-level security policy for table tenants."
- After bootstrap, the *current* token still lacked the claim, so `/auth/me` re-entered the new-user branch and created a **second tenant** → duplicate `pk_users` → 500.

**Fixes:**
- `app/modules/auth/service.py::bootstrap()` — pre-generate `uuid.uuid4()`, call `set_tenant(db, str(new_tenant_id))` **before** `db.flush()`. Added `_admin_tenant_id()` guard: if the token has no `tenant_id`, consult the Supabase admin API first so a stale/replayed token reuses the existing tenant instead of spawning a duplicate.
- `frontend/app/{login,signup}/page.tsx` — call `await supabase.auth.refreshSession()` right after `apiBootstrap()` so the new token carries `tenant_id` before any tenant-scoped call.

**New file:** `frontend/app/signup/page.tsx` — signup flow is `apiSignup` → `signInWithPassword` → `apiBootstrap` → `refreshSession` → `router.push("/dashboard")`.

---

## Problem 2 — Sidebar storage meter didn't update after upload

**Symptom:** After uploading a document, the **dashboard** storage bar increased but the **sidebar** storage bar stayed the same until a full page reload.

**Root cause:** The auth context (`frontend/lib/auth.tsx`) fetches the tenant once on mount and never re-fetches. Both the dashboard and the sidebar read the same `tenant.storage_used_bytes` counter (incremented at upload time in `files/service.py`), but only the dashboard page re-queried it on navigation — the sidebar reads the stale in-memory context value.

**Fix:**
- `frontend/lib/auth.tsx` — expose a `refresh()` callback (re-runs `apiMe()` and updates `user`/`tenant`) via the auth context; keeps last-known values on transient failure so the UI never blanks.
- `frontend/app/(app)/upload/page.tsx` — after a successful upload that actually stored bytes (not a dedup hit), call `await refresh()` so the sidebar meter updates immediately.

---

## Infra / tooling fix

`start-system.ps1` — corrected the backend launch to `python -m uvicorn app.main:app --reload --port 8000` and the worker launch to `python -m app.worker` (the previous `python -m worker.runner` path is from the sibling root project layout and does not exist here).

---

## Verification

**Backend — verified end-to-end via curl:**
`signup → signin → bootstrap → refresh_token → /me + /dashboard + /documents` all returned **200**. Bootstrap replay with a stale token **reused the same tenant** (no duplicate tenant, no `pk_users` 500).

**Frontend:** All touched files hot-reloaded clean; `getDiagnostics` showed no TypeScript errors.

---

## End state

- Signup works end-to-end (create account → auto sign-in → dashboard).
- Sidebar + dashboard storage meters stay in sync after upload.
- Canonical port is **8000** across backend, frontend, and `start-system.ps1`.

## Next / outstanding

- **Cleanup of synthetic test accounts** (`@datawiz-test.local` + `test@example.com`) — still pending; the user prefers to control how this is run rather than have a script executed against Supabase Auth directly.
- User to perform the final manual smoke test of the signup + storage-meter fixes.
