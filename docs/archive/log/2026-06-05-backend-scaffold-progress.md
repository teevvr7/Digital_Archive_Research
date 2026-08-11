# Daily Progress Log — 2026-06-05

**Session:** Backend MVP Scaffold + Architecture Plan
**Status:** Milestone A (Walking Skeleton) — code complete, pending Supabase setup + `npm install`

---

## What Was Done Today

### 1. Architecture Plan (Finalised)

After multiple rounds of refinement, the full MVP plan was approved. Key decisions locked:

| Decision | Choice |
|---|---|
| DB / Auth / Storage | Supabase (managed Postgres + RLS + Auth + Storage) |
| PDF/Doc Parsing | **LiteParse** (LlamaIndex, Rust, local — replaces PyMuPDF+PaddleOCR) |
| AI Extraction | Self-hosted **vLLM on Lightning AI Studio** (OpenAI-compatible endpoint) |
| Doc types | **Dynamic** — types/templates stored as DB data, not code |
| Multi-tenancy | Postgres RLS via custom GUC `app.current_tenant` (per-transaction, fail-closed) |

Key architectural insight from owner:
> The IDP pipeline must be **self-learning**: unknown docs → VLM → store output + learn template → promote to deterministic (CPU) path after N confirmations. Doc types are never hardcoded — the system learns them.

Reference diagram: `image.png` in project root (the cost cascade flowchart).

---

### 2. Backend — Files Created

```
backend/
├── pyproject.toml              Python deps (base + [worker] + [dev] groups)
├── .env.example                All env vars documented
├── Dockerfile                  Lean API image (no heavy parsing deps)
├── Dockerfile.worker           Worker image + LiteParse + ImageMagick
├── docker-compose.yml          Redis only (Supabase is cloud)
├── alembic.ini
└── app/
    ├── main.py                 FastAPI app + CORS + auth router
    ├── worker.py               RQ worker entrypoint
    ├── core/
    │   ├── config.py           pydantic-settings (all env vars)
    │   ├── camel.py            CamelModel base (snake→camelCase auto-alias)
    │   ├── db.py               SQLAlchemy engine (psycopg3, prepared statements off)
    │   ├── tenant_context.py   tenant_session() — SET LOCAL app.current_tenant GUC
    │   ├── security.py         Supabase JWT verify (HS256)
    │   ├── deps.py             get_current_user, get_tenant_db, require_admin
    │   └── storage.py          Supabase Storage adapter (upload/download/signed URL)
    ├── models/
    │   ├── base.py             DeclarativeBase + TimestampMixin + uuid_pk
    │   ├── tenant.py
    │   ├── user.py
    │   ├── document.py
    │   ├── document_type.py    Dynamic catalog (types as data)
    │   ├── document_template.py Learned layouts (candidate→promoted→disabled)
    │   ├── extraction.py       Extraction history (powers exception queue + learning)
    │   ├── processing_job.py   Pipeline run tracking
    │   ├── activity_event.py
    │   └── api_key.py
    ├── modules/
    │   └── auth/
    │       ├── router.py       GET /auth/me, POST /auth/bootstrap
    │       ├── service.py      First-login tenant+user sync
    │       └── schemas.py      UserOut, TenantOut, MeOut (camelCase)
    ├── migrations/
    │   ├── env.py              Alembic env (uses ALEMBIC_DATABASE_URL)
    │   └── versions/
    │       ├── 0001_initial_tables.py       All 9 tables + all indexes
    │       ├── 0002_rls_policies.py         ENABLE + FORCE RLS + tenant_isolation policies
    │       └── 0003_seed_system_document_types.py  Seed invoice/receipt/contract/etc.
    └── tests/
        ├── test_tenant_isolation.py         7 isolation assertions (mandatory)
        └── test_contract_camelcase.py       Ensures no snake_case fields leak to UI
```

### 3. Frontend — Changes Made

| File | Change |
|---|---|
| `frontend/lib/supabase.ts` | New — Supabase client (for when backend is wired) |
| `frontend/lib/api.ts` | New — typed API client with Bearer auth (for when backend is wired) |
| `frontend/package.json` | Added `@supabase/supabase-js` (not yet installed — run `npm install`) |
| `frontend/.env.local.example` | New — template for Supabase + API URL env vars |
| `frontend/app/login/page.tsx` | **Reverted to mock mode** — demo credentials, 1.2s simulated auth |

> **Note:** `lib/supabase.ts` and `lib/api.ts` exist but are NOT imported anywhere yet.
> Frontend is fully standalone mock mode. Wire by importing in each page when the backend is ready.

---

## Database Schema Summary (9 tables)

| # | Table | Purpose |
|---|-------|---------|
| 1 | `tenants` | Organisation, plan, storage accounting |
| 2 | `users` | App profile (mirrors Supabase auth user) |
| 3 | `documents` | Central archive: metadata, status, storage_key, extracted_data (JSONB) |
| 4 | `document_types` | **Dynamic catalog** — types as data, not code (`tenant_id NULL` = system type) |
| 5 | `document_templates` | Learned layouts: fingerprint + field_mappings + promotion lifecycle |
| 6 | `extractions` | Every extraction attempt — powers exception queue + promote-after-N |
| 7 | `processing_jobs` | Pipeline run tracking (stage, attempts, timing, error) |
| 8 | `activity_events` | Audit trail + dashboard activity feed |
| 9 | `api_keys` | Settings — hashed keys only |

Exception queue = query over `extractions WHERE status='low_confidence'` (not a separate table).

---

## RLS Mechanism (The Multi-Tenancy Core)

```
Per-request:
  1. FastAPI dep opens transaction
  2. SELECT set_config('app.current_tenant', tenant_id, true)   ← transaction-local
  3. All queries run — RLS policy: tenant_id = current_setting('app.current_tenant', true)::uuid
  4. Commit/rollback → GUC auto-discarded

No GUC → current_setting(..., true) = NULL → policy fails → 0 rows (FAIL CLOSED)
```

- Transaction pooler (6543) for API — psycopg3 `prepare_threshold=None`
- Direct connection (5432) for Alembic migrations only

---

## IDP Pipeline (Cost Cascade — from image.png)

```
Incoming file
    ↓
Get text (LiteParse: text layer → skip OCR; else OCR)
    ↓
Classify + fingerprint (user hint + heuristic; Phase 2: auto-classify)
    ↓
Known layout?
    ├─ YES → Deterministic extract (CPU, field_mappings) ──────────┐
    └─ NO  → VLM → JSON (vLLM/Lightning AI)                       │
                  ↓ low confidence                                  │
              Exception queue                    promote after N ◄──┘
                  ↓ accepted
Store JSON + index (search_tsv, JSONB GIN)
```

MVP = VLM-first for all docs (deterministic path is stubbed). Learning data captured from day 1.
Phase 2 = promote templates → deterministic path → GPU cost drops.

---

## Approved MVP Plan (Milestones)

| Milestone | Sprint | Theme | Key Deliverable |
|---|---|---|---|
| A | 0 | Walking skeleton | Login works end-to-end; UI shows real user |
| B | 1 | Ingestion + isolation | Upload→store→list→download; **isolation tests green** |
| C | 2 | LiteParse + VLM extraction | Real pipeline; status badges animate through real states |
| D | 3 | Search + learning scaffolding | Search <2s; exception queue; template candidates |
| E | 4 | Hardening | `app_user` role; admin guards; Sentry; CORS locked |
| — | Phase 2 | Self-learning | Deterministic path; promote-after-N; auto-classify |

---

## What To Do Next (Milestone A Completion)

To finish the walking skeleton you need to:

1. **Create a Supabase project** at supabase.com
   - Enable `pgcrypto` and `pg_trgm` extensions (Database → Extensions)
   - Create a `documents` storage bucket (Storage → New bucket, private)
   - Copy: Project URL, anon key, service role key, JWT secret, DB connection strings

2. **Fill in `.env` files**
   - `backend/.env` — copy from `backend/.env.example`, fill in Supabase values + VLM endpoint
   - `frontend/.env.local` — copy from `frontend/.env.local.example`, fill in Supabase URL + anon key

3. **Install backend dependencies**
   ```bash
   cd backend
   pip install -e ".[dev]"
   ```

4. **Run Alembic migrations** (creates all tables + RLS)
   ```bash
   cd backend
   alembic upgrade head
   ```

5. **Install frontend Supabase package**
   ```bash
   cd frontend
   npm install
   ```

6. **Start Redis** (needed for the job queue)
   ```bash
   cd backend
   docker-compose up redis
   ```

7. **Start the API**
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```

8. **Test the walking skeleton** — create a user in Supabase Auth dashboard, open
   `http://localhost:3000`, log in, confirm `/auth/me` returns real user + tenant data.

---

## Key Risks to Watch

| Risk | Mitigation |
|---|---|
| Pooler + prepared statements | psycopg3 `prepare_threshold=None` already set |
| RLS owner bypass | FORCE RLS on all tables; hardening adds non-owner `app_user` role |
| Dynamic schema crashes | `extracted_data: dict[str,Any]` — soft validation only, never rejects |
| vLLM endpoint sleeping (Lightning AI) | RQ retries; degrade to `failed` with text still searchable |
| camelCase drift | `CamelModel` base + `test_contract_camelcase.py` |
| LiteParse beta | Pin version in pyproject.toml; PyMuPDF fallback if needed |
