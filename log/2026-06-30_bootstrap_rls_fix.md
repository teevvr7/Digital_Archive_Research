# Bug Fix — Bootstrap RLS Regression
**Date:** 2026-06-30  
**Symptom:** Login page showed "Backend bootstrap failed: Failed to fetch" (HTTP 500, no body, no CORS headers)  
**Root cause:** Phase 0 removed `BYPASSRLS` from `app_user` but the auth bootstrap path was never updated to set the tenant GUC before writing to the DB.

## What broke

`auth/service.py::bootstrap()` opens a raw `SessionLocal()` (no GUC set) and tries to:
1. `db.get(Tenant, uuid)` — SELECT blocked by RLS → returns `None`
2. Falls into the "edge case: tenant row missing" branch → tries `INSERT INTO tenants`
3. INSERT blocked by RLS policy `WITH CHECK (id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)`
4. `InsufficientPrivilege` exception → SQLAlchemy unhandled → 500 with no CORS headers → browser shows "Failed to fetch"

The old 8-day-old process (PID 16276, started 2026-06-22) was also masking the issue — it was running pre-Phase-0 code that had `BYPASSRLS` still in effect.

## Fix (`app/modules/auth/service.py`)

Three changes:
1. **Set GUC before first write (new user path):** call `set_tenant(db, str(tenant.id))` after `db.flush()` materialises the new UUID, before the Supabase admin call.
2. **Set GUC before first read (returning user path):** call `set_tenant(db, token.tenant_id)` before `db.get(Tenant, ...)` so both the SELECT and any edge-case INSERT pass RLS.
3. **Re-apply GUC after commit:** `db.commit()` ends the transaction and resets all transaction-local GUCs. Saved `final_tenant_id = str(tenant.id)` before commit, then call `set_tenant(db, final_tenant_id)` before `db.refresh(user)` / `db.refresh(tenant)`.

## Also fixed during investigation

- `config.py` CORS default expanded to include `http://127.0.0.1:3000` and `http://[::1]:3000` alongside `http://localhost:3000` — prevents origin mismatch when browser accesses frontend via IP.
- Backend restart pattern: always kill by `Get-Process python | Kill()` not by PID from `netstat` (stale PIDs persist in netstat after process exit on Windows).
- Backend should be started with `--host 0.0.0.0` not the default `127.0.0.1` to cover all network interfaces on Windows.
