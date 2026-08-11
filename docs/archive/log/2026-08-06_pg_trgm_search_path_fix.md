# Incident Report: `word_similarity` Function Not Found — Search & Document Listing Failure

**Date:** 2026-08-06  
**Severity:** High — Search and document filtering completely broken  
**Status:** Resolved  

---

## 1. Symptoms

When using the **Documents** page or **Search** page in the frontend, any search query (e.g. typing "slack" in the search bar) resulted in:

- **Frontend:** `TypeError: Failed to fetch` in the browser console, originating from `lib/api.ts:108` inside the `put()` / `get()` helper.
- **Backend (Uvicorn terminal):** A full Python traceback ending with:

```
sqlalchemy.exc.ProgrammingError: (psycopg.errors.UndefinedFunction)
function word_similarity(character varying, text) does not exist
```

The error was thrown at `backend/app/modules/files/service.py:941` inside `list_documents()`, during the count query that wraps the search subquery.

**Crucially**, basic document listing (without a search term) worked fine — data populated from Supabase. Only queries involving **fuzzy text search** failed.

---

## 2. Root Cause Analysis

The failure involved **four interacting layers**. Each one is necessary to understand the full picture.

### Layer 1: PostgreSQL Extension Location

PostgreSQL's `word_similarity()` function comes from the **`pg_trgm`** extension (trigram matching). On Supabase-hosted PostgreSQL databases, extensions are installed into a dedicated schema called **`extensions`** — not into `public`.

```sql
-- Where pg_trgm lives on Supabase:
SELECT extname, extnamespace::regnamespace FROM pg_extension WHERE extname = 'pg_trgm';
-- Result: pg_trgm | extensions
```

This is a Supabase design choice to keep the `public` schema clean for user tables.

### Layer 2: Role-Specific `search_path` Mismatch

PostgreSQL resolves unqualified function names (like `word_similarity(...)`) by scanning schemas listed in the session's `search_path`. Different database roles can have different default `search_path` values.

| Role | Default `search_path` | Can find `word_similarity()`? |
|---|---|---|
| `postgres` (superuser) | `"$user", public, extensions` | **Yes** — `extensions` is in the path |
| `app_user` (application role) | `"$user", public` | **No** — `extensions` is **missing** |

The backend's `DATABASE_URL` connects as **`app_user`**, not `postgres`. So every query the backend runs goes through a role that **cannot see** functions in the `extensions` schema.

### Layer 3: PgBouncer Transaction Pooler Blocks the Obvious Fix

The natural fix would be:

```sql
ALTER ROLE app_user SET search_path TO "$user", public, extensions;
```

This was executed successfully. However, the backend connects through **Supabase's transaction pooler** on port `6543`. This pooler is powered by **PgBouncer in transaction pooling mode**.

In transaction pooling mode, PgBouncer:
- Shares a pool of backend PostgreSQL connections across many clients.
- **Resets all session-level state** (including `search_path`) between transactions.
- Does **not** honor `ALTER ROLE ... SET` because the pooled backend connection was originally established under a different role/session.

So even though `ALTER ROLE app_user SET search_path` was committed to PostgreSQL's catalog, PgBouncer's pooled connections never pick it up.

**This is the core of the bug: a Supabase architectural detail (extensions in a separate schema) combined with PgBouncer's transaction pooling behavior (session state reset) made `pg_trgm` functions invisible to the application.**

### Layer 4: How This Surfaced as "Failed to fetch" in the Browser

The chain of events on every search request:

```
Browser sends GET /api/documents?search=slack
    → FastAPI receives the request
        → service.list_documents() builds a SQL query using word_similarity()
            → SQLAlchemy sends the query to PostgreSQL (via PgBouncer)
                → PostgreSQL: "function word_similarity does not exist" → ERROR
            → SQLAlchemy raises ProgrammingError
        → FastAPI returns HTTP 500 (Internal Server Error)
            → The 500 response may lack CORS headers (depending on error handler)
    → Browser sees missing CORS headers or 500 status
        → fetch() rejects the promise
            → Frontend catch block shows "Failed to fetch"
```

The misleading part: the browser error says "Failed to fetch" — which sounds like a network/CORS problem — when the actual root cause is a **missing PostgreSQL schema in the search path**.

---

## 3. Diagnostic Process

### Step 1: Read the Uvicorn Traceback

The backend terminal showed the exact SQL error: `function word_similarity(character varying, text) does not exist`. This pointed directly at `pg_trgm`.

### Step 2: Verify pg_trgm Was Installed

Connected as `postgres` (superuser) and confirmed:

```sql
SELECT extname, extversion, extnamespace::regnamespace FROM pg_extension WHERE extname = 'pg_trgm';
-- Result: pg_trgm | 1.6 | extensions
```

`pg_trgm` **was** installed. The function existed. So why couldn't the backend find it?

### Step 3: Compare Connection Contexts

Ran a diagnostic script that connected as both `postgres` and `app_user`, comparing their `search_path` and ability to call `word_similarity()`:

```
postgres role:  search_path = "$user", public, extensions  → word_similarity() WORKS
app_user role:  search_path = "$user", public              → word_similarity() FAILS
```

**Root cause identified**: `app_user` doesn't have `extensions` in its `search_path`.

### Step 4: Test Fixes Through PgBouncer

Tested three approaches to inject `extensions` into the search path through PgBouncer's transaction pooler:

| Approach | Method | Result |
|---|---|---|
| `ALTER ROLE SET search_path` | Server-side role default | **Failed** — PgBouncer ignores role defaults |
| `SET search_path` within transaction | Per-transaction statement | **Works** |
| URL `?options=-c search_path=...` | Connection parameter | **Works** |
| SQLAlchemy `"connect"` event listener | Per-connection hook | **Works** |

---

## 4. The Fix

### File Modified: `backend/app/core/db.py`

Added a SQLAlchemy **connection event listener** that runs `SET search_path` on every new database connection established by the connection pool:

```python
from sqlalchemy import create_engine, event, text  # added 'event' and 'text'

# ... (engine creation unchanged) ...

engine = _make_engine()

# --- search_path fix for Supabase + PgBouncer transaction pooler ---
# Supabase installs extensions (pg_trgm, etc.) in the 'extensions' schema.
# PgBouncer's transaction pooler resets session state between transactions,
# so ALTER ROLE SET search_path doesn't persist. This listener runs
# SET search_path on every fresh connection checkout from the pool.
@event.listens_for(engine, "connect")
def _set_search_path(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute('SET search_path TO "$user", public, extensions')
    cursor.close()
```

### Why This Approach

- **`"connect"` event fires once per physical connection** — when SQLAlchemy's pool creates a new connection to PostgreSQL (via PgBouncer). It does not fire on every checkout from the pool, so overhead is minimal.
- **Works with PgBouncer transaction mode** — the `SET` runs at the DBAPI level before SQLAlchemy uses the connection, and PgBouncer respects `SET` commands issued within a session.
- **Zero `.env` changes required** — the fix lives in code, not in a URL parameter that could be forgotten during deployment.
- **Future-proof** — any new extensions installed in the `extensions` schema (e.g., `pg_trgm`, `pgcrypto`, `uuid-ossp`) will automatically be accessible.

---

## 5. Verification

After restarting Uvicorn with the updated `db.py`:

1. **Search on Documents page** — typing "slack" returns matching documents with no errors.
2. **Search page** — full-text + fuzzy search works correctly.
3. **Uvicorn terminal** — no more `UndefinedFunction` tracebacks; requests return `200 OK`.

---

## 6. Key Takeaways

1. **Supabase installs extensions in a separate `extensions` schema**, not `public`. This is different from a standard self-hosted PostgreSQL setup where `CREATE EXTENSION` defaults to `public`.

2. **PgBouncer's transaction pooler resets session state** between transactions. Role-level `SET search_path` defaults do not persist across pooled connections.

3. **"Failed to fetch" in the browser is often a backend error**, not a network or CORS issue. When FastAPI throws an unhandled 500 error, the response may lack CORS headers, causing the browser to mask the real error.

4. **The `app_user` role used by the application has a more restrictive `search_path`** than the `postgres` superuser role. Always test database features using the same role the application connects with.

---

## 7. Architecture Diagram

```
Browser (localhost:3000)
    │
    │  GET /api/documents?search=slack
    │
    ▼
Next.js Frontend (lib/api.ts)
    │
    │  fetch("http://localhost:8000/api/documents?search=slack")
    │
    ▼
FastAPI Backend (Uvicorn, port 8000)
    │
    │  service.list_documents() → SQLAlchemy query with word_similarity()
    │
    ▼
SQLAlchemy Engine (db.py)
    │
    │  ┌─────────────────────────────────────────────────┐
    │  │ NEW: @event.listens_for(engine, "connect")      │
    │  │ SET search_path TO "$user", public, extensions   │
    │  └─────────────────────────────────────────────────┘
    │
    ▼
PgBouncer Transaction Pooler (port 6543)
    │  Role: app_user
    │  search_path: "$user", public, extensions  ← now includes 'extensions'
    │
    ▼
Supabase PostgreSQL
    ├── public schema     → documents, tenants, etc.
    └── extensions schema → pg_trgm (word_similarity), pgcrypto, etc.
```

---

*Report generated: 2026-08-06 01:04 SGT*
