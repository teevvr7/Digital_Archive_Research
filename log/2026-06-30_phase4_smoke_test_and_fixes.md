# 2026-06-30 — Phase 4 Smoke Test & Bug Fixes

**Branch:** `mvp-lvl2`  
**Status at end of day:** Phase 4 fully complete ✅ — 161/161 tests, smoke test passed, pipeline running

---

## What was done today

### 1. Bootstrap RLS fix (login broken)

**Symptom:** Logging in returned "Backend bootstrap failed: Failed to fetch" (HTTP 500, no body, no CORS headers).

**Root cause:** Phase 0 removed `BYPASSRLS` from `app_user`, but `auth/service.py::bootstrap()` opened a raw `SessionLocal()` with no GUC set — so RLS blocked both the `SELECT` and `INSERT INTO tenants`.

**Fix in `app/modules/auth/service.py`** (three changes):
1. Set GUC before first write on new-user path: `set_tenant(db, str(tenant.id))` after `db.flush()`
2. Set GUC before first read on returning-user path: `set_tenant(db, token.tenant_id)` before `db.get(Tenant, ...)`
3. Capture `final_tenant_id = str(tenant.id)` before `db.commit()` (SQLAlchemy expires attributes on commit), then re-apply GUC after commit for the refresh queries

Also expanded `cors_allow_origins` in `config.py` to include `127.0.0.1:3000` and `[::1]:3000` alongside `localhost:3000`.

See full detail: `logs/2026-06-30_bootstrap_rls_fix.md`

---

### 2. Upload fix (Redis not running)

**Symptom:** Upload returned "Failed to fetch" (HTTP 500).

**Root cause:** Redis was not running — Docker Desktop hadn't been started.

**Fix:** Start Docker Desktop → `docker run -d --name redis -p 6379:6379 redis:7-alpine`

---

### 3. Worker auto-matching SQL bug (documents stuck in `queued`)

**Symptom:** Uploaded documents stayed in `queued` status forever. Worker started and logged "Listening on idp..." but never processed any jobs. 24 jobs were piling up in the `rq:scheduled:idp` sorted set.

**Root cause:** `app/modules/tags/matching.py` used SQLAlchemy's generic `.prefix_with("ON CONFLICT ...")` which generates:
```sql
INSERT ON CONFLICT (document_id, tag_id) DO NOTHING INTO document_tags ...  -- INVALID
```
This aborted the PostgreSQL transaction on every job. The crash-isolation try/except in `jobs.py` swallowed the error, but the aborted transaction then caused the final `db.commit()` to raise `InFailedSqlTransaction`, crashing the whole job. RQ's `Retry(max=3)` cycled each job into the scheduled retry registry. Since RQ `SimpleWorker` on Windows doesn't auto-promote overdue scheduled jobs, all 24 jobs were stuck.

**Fix in `app/modules/tags/matching.py`:**
```python
# Before (wrong):
from sqlalchemy import insert
.prefix_with("ON CONFLICT (document_id, tag_id) DO NOTHING")

# After (correct):
from sqlalchemy.dialects.postgresql import insert
.on_conflict_do_nothing(index_elements=["document_id", "tag_id"])
```

**One-time recovery:** Manually promoted the 24 stuck scheduled jobs back to the active queue via `ScheduledJobRegistry.get_jobs_to_schedule()` + `.requeue()`.

See full detail: `logs/2026-06-30_worker_matching_fix.md`

---

## Smoke test results

| Step | Result |
|---|---|
| Login (email + password) | ✅ Working |
| Upload a PDF (`big-invoice.pdf`) | ✅ Uploaded, status=`completed`, confidence=0.91 |
| Worker text extraction | ✅ `extracted_text` populated |
| Tags page (`/tags`) — CRUD | ✅ Create/edit/delete working |
| Correspondents page (`/correspondents`) — CRUD | ✅ Create/edit/delete working |
| Documents list — tag filter dropdown | ✅ Working |
| Document detail — inline tag assign/unassign | ✅ Working |
| Document detail — correspondent shown in Metadata tab | ✅ Working |
| Auto-matching (tag + correspondent on upload) | ✅ Working after SQL bug fix |

---

## End state

- **Tests:** 161/161 passing
- **Migration:** `0009_tags_correspondents` applied and live
- **Worker:** running, picking up jobs, pipeline completes end-to-end
- **Phase 4:** Complete ✅

## Next

**Phase 5 — Metadata:** custom-field catalog + typed values (JSONB hybrid) + correction UI for extracted fields.
