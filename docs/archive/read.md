# DataWiz Digital Archive — Complete Project Reference

> Full technical and plain-English documentation of everything built and everything planned.

---

## Table of Contents

**[How to Run the System](#how-to-run-the-system)** — start here if you just want it running.

**Part 1 — Technical Reference**
1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Database Schema](#4-database-schema)
5. [Security & Multi-Tenancy](#5-security--multi-tenancy)
6. [Backend API — All Endpoints](#6-backend-api--all-endpoints)
7. [IDP Pipeline — Tier by Tier](#7-idp-pipeline--tier-by-tier)
8. [Search System](#8-search-system)
9. [Queue & Worker](#9-queue--worker)
10. [Frontend](#10-frontend)
11. [Configuration Reference](#11-configuration-reference)
12. [Testing](#12-testing)
13. [Project File Structure](#13-project-file-structure)

**Part 2 — Plain-English Guide**
14. [What is DataWiz?](#14-what-is-datawiz)
15. [How It Works — Step by Step](#15-how-it-works--step-by-step)
16. [What's Already Built](#16-whats-already-built)
17. [What's Coming Next](#17-whats-coming-next)

---

## How to Run the System

### Prerequisites

- Python 3.11+
- Node.js 18+ and npm
- Redis (local install, or `docker run -p 6379:6379 redis`)
- A Supabase project (free tier is enough) — gives you Postgres, Auth, and Storage in one place

### 1. Environment files

```bash
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local
```

Fill in `backend/.env` from your Supabase project (Project Settings → API / Database):
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`,
`DATABASE_URL` (transaction pooler, port 6543), `ALEMBIC_DATABASE_URL` (direct connection, port
5432). Everything else in `.env.example` has a working default. `VLM_BASE_URL` can stay empty —
AI extraction is simply skipped (documents that need it fall through to `needs_review`) until a
Lightning AI Studio endpoint is deployed. Fill `frontend/.env.local` with the matching
`NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` (`NEXT_PUBLIC_API_BASE_URL` defaults
to `http://localhost:8000/api`, correct for local dev). Never commit either `.env` file.

### 2. Install dependencies

```bash
# Backend (installs the API + worker + dev/test tooling in one venv for local dev)
cd backend
python -m venv venv
./venv/Scripts/Activate.ps1        # Windows PowerShell — use `source venv/bin/activate` on macOS/Linux
pip install -e ".[worker,dev]"
cd ..

# Frontend
cd frontend
npm install
cd ..
```

### 3. Apply database migrations

```bash
cd backend
alembic upgrade head        # current head: 0016 — see §4.3 for the full list
```

This connects as `ALEMBIC_DATABASE_URL` (the `postgres` superuser, direct port 5432 — needs DDL
privileges the live app's `app_user` role deliberately doesn't have). Re-run this any time you
pull new migrations.

### 4. Start all three processes

Either use the convenience script from the repo root (Windows):

```powershell
./start-system.ps1
```

It installs missing dependencies automatically, then opens three PowerShell windows: backend API
(port 8000, with `--reload`), worker, and frontend (port 3000).

...or start each manually, in three terminals:

```bash
# Terminal 1 — API
cd backend && ./venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — worker (polls the Redis "idp" queue; needs the [worker] extra installed)
cd backend && ./venv/Scripts/python.exe -m app.worker

# Terminal 3 — frontend
cd frontend && npm run dev
```

Then open `http://localhost:3000`, sign up, and the first login auto-bootstraps your tenant —
no manual setup needed.

### 5. Run the tests

```bash
cd backend
./venv/Scripts/python.exe -m pytest app/tests -v      # 394 tests — use the venv's own interpreter,
                                                        # not a bare `python`, or app.main-importing
                                                        # tests silently fail (see §12)
python eval/run.py                                     # deterministic pass rate + LLM share
```

```bash
cd frontend
npm run lint
npx tsc --noEmit
```

### Troubleshooting

- **Uvicorn `--reload` can silently serve stale code** after certain file changes (observed in
  dev — a route addition looked like a 404 when it was actually just not reloaded). If a route
  you just added looks missing, restart uvicorn **without** `--reload` once to confirm; if that
  fixes it, it was a stale-reload issue, not a real bug. A quick way to tell "route doesn't exist"
  (404) apart from "route exists but auth/tenant failed" (401) is to hit it with no `Authorization`
  header — a 401 confirms the route is actually registered.
- **Redis not running** → the worker will fail to connect and the API's rate limiter fails open
  (logs a warning, lets requests through) rather than 500ing — uploads will queue but never
  process until Redis is back.
- **`VLM_BASE_URL` empty** → this is expected until a GPU endpoint is deployed (see §17); the
  pipeline degrades gracefully, marking hard documents `needs_review` instead of blocking.

---

# Part 1 — Technical Reference

---

## 1. Project Overview

**DataWiz Digital Archive** is a multi-tenant SaaS document archive system with an Intelligent Document Processing (IDP) pipeline. It ingests **any file type** — PDFs, scans, images, Office documents, text/CSV/Markdown, email, and now e-invoice XML — stores it securely, extracts text and structured data automatically, and makes everything fast and searchable. Structured invoice/receipt extraction is a cost-saving enhancement layered on top; every file gets full ingestion, text, thumbnail, and search regardless of type.

**Design principle — the 10–15% AI rule:**
Deterministic code (parsing, OCR, regex/rule-based field extraction, full-text search) handles ~85–90% of the work. A quality **gate** (`idp/gate.py`, pass threshold `0.75`) decides whether a document's deterministic extraction is good enough to accept. The VLM is the exception handler — it only ever runs after the gate has failed a document, targeting 10–20% of structured-extraction candidates. This keeps infrastructure cost near zero and is a hard architectural rule, not a tuning knob.

**Cost cascade (cheapest first):**
1. Parse (free) — PyMuPDF for PDFs with a text layer, `python-docx`/`openpyxl`/`python-pptx` for Office formats, direct decode for text/CSV/Markdown, stdlib `email`/`xml.etree` for `.eml` and UBL/MyInvois XML
2. OCR (cheap, CPU) — RapidOCR, only when no usable text layer exists
3. Deterministic field extraction (CPU, ~$0) — regex/keyword rules (or, for UBL-XML, direct structured parsing) scored by the quality gate; **score ≥ 0.75 → accepted, no AI involved**
4. VLM fallback (GPU/network, the exception handler) — only on gate-fail, target 10–20% of documents
5. Search → Postgres FTS + trigram + structured metadata filters — **no external search cluster**

**Target infrastructure cost:** ~$0/month (Supabase free tier + Lightning AI Studio GPU only when the gate fails).

**Deployment:**
- Database + Auth + Storage: [Supabase](https://supabase.com) (PostgreSQL, pgvector, RLS, Storage)
- VLM endpoint: [Lightning AI Studio](https://lightning.ai) (vLLM serving Qwen3-VL-4B-Instruct, OpenAI-compatible API)
- API + Worker: can run locally or on any Linux server (Render free tier compatible)
- Frontend: Next.js, deployable on Vercel free tier

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Browser (Next.js :3000)                       │
│  Login/Signup/Invite-accept → Supabase Auth SDK → JWT           │
│  Every API call: Authorization: Bearer <JWT>                     │
└─────────────────────┬───────────────────────────────────────────┘
                      │ HTTPS / JWT
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                 FastAPI Backend (:8000)                          │
│  CORS + rate limiting (slowapi, Redis-backed) + Sentry           │
│  12 routers, all mounted under /api — see §6 for the full list:  │
│  auth, files/documents, dashboard, search, tags, correspondents, │
│  metadata (custom fields), views (saved views), export, shares   │
│  (+ one public unauthenticated route: GET /api/share/{token})    │
│                                                                 │
│  Every authenticated route:                                     │
│   1. verify_token(Bearer JWT) → TokenData                       │
│   2. db.begin() → SET LOCAL app.current_tenant = :tenant_id    │
│   3. RLS enforces tenant boundary on every SQL query,           │
│      via a dedicated non-bypassrls `app_user` Postgres role     │
└──────────────┬──────────────────────────────┬───────────────────┘
               │ SQLAlchemy + psycopg3         │ enqueue (Redis)
               ▼                              ▼
┌──────────────────────────┐   ┌─────────────────────────────────┐
│  PostgreSQL (Supabase)   │   │      Redis Queue  (idp)         │
│  17 tables, RLS on all   │   └──────────────┬──────────────────┘
│  tenant-owned ones —     │                  │ RQ job
│  see §4 for full schema  │                  ▼
│  (tenants, users, docs,  │   ┌─────────────────────────────────┐
│  document_types/         │   │   Worker (python -m app.worker) │
│  templates, extractions, │◄──│                                 │
│  processing_jobs,        │   │  Tier 0: parse (PyMuPDF/Office/ │
│  activity_events,        │   │    text/email/UBL-XML parsers)  │
│  api_keys, ai_usage,     │   │  Tier 1: RapidOCR (if needed)   │
│  tags, document_tags,    │   │  Tier 2: deterministic extract  │
│  correspondents,         │   │    + quality gate (0.75)        │
│  custom_fields,          │   │  Tier 4: VLM — gate-fail ONLY   │
│  document_field_values,  │   │  Populate search_tsv, thumbnail,│
│  saved_views,            │   │  typed columns, auto-tag/link   │
│  document_shares)        │◄──│  → doc.status = 'completed'     │
└──────────────────────────┘   └─────────────┬───────────────────┘
                                              │ download_file / upload_file
                                              ▼
                               ┌─────────────────────────────────┐
                               │   Supabase Storage (S3)         │
                               │   tenants/{tid}/{sha256}         │
                               └─────────────────────────────────┘
                                             │ OpenAI API call (gate-fail only)
                                             ▼
                               ┌─────────────────────────────────┐
                               │  Lightning AI Studio (vLLM)     │
                               │  Qwen-VL class, OpenAI-compat   │
                               │  Tier 4 exception handler only  │
                               └─────────────────────────────────┘
```

**Request lifecycle (upload example):**
1. Browser POSTs multipart form to `POST /api/documents`
2. FastAPI verifies JWT, opens DB session, sets GUC tenant
3. File bytes uploaded to Supabase Storage (content-addressed by sha256, deduped); `Document` + `ProcessingJob` rows inserted; `ActivityEvent(upload)` logged
4. After commit, `enqueue_document(doc_id, tenant_id)` pushes an RQ job to Redis
5. Worker picks up the job: downloads file bytes from storage, runs the parse → OCR → deterministic-extract-and-gate → (VLM only on gate-fail) cascade, populates `extracted_text`, `extracted_data`, typed columns (`vendor`/`invoice_no`/`total_amount`/`currency`), thumbnail, `search_tsv`, runs auto-tag/auto-link matching, sets `status = completed` (or `needs_review` if extraction was attempted but never accepted)
6. Frontend polls `GET /api/documents/{id}` every 3 seconds; once status leaves the in-flight set, stops polling and renders the Extracted Data tab

---

## 3. Technology Stack

### Backend

| Package | Version | Purpose |
|---|---|---|
| Python | ≥3.11 | Runtime; type hints everywhere |
| FastAPI | ≥0.115 | HTTP framework; async request handlers |
| Uvicorn | ≥0.30 | ASGI server (`uvicorn[standard]` for websocket + HTTP/2) |
| python-multipart | ≥0.0.9 | Multipart form parsing for file uploads |
| Pydantic v2 | ≥2.7 | Data validation, serialization, settings; `CamelModel` for API output |
| pydantic-settings | ≥2.3 | Typed settings loaded from `.env` |
| SQLAlchemy | ≥2.0 | ORM + Core query builder; `future=True` (2.x API) |
| Alembic | ≥1.13 | Database migrations; 5 revisions applied |
| psycopg[binary] | ≥3.2 | PostgreSQL driver (psycopg3); `prepare_threshold=None` for transaction pooler |
| PyJWT[crypto] | ≥2.8 | JWT verification (HS256 + ES256/RS256 via JWKS); `cryptography` included |
| Redis | ≥5.0 | Redis client for RQ |
| RQ | ≥1.16 | Redis Queue job system; `SimpleWorker` on Windows, `Worker` on Linux |
| Supabase | ≥2.5 | Python client for Storage (upload/download/signed URL) + Auth Admin (user patching) |
| httpx | ≥0.27 | HTTP client (used internally by supabase-py) |
| python-dotenv | ≥1.0 | `.env` file loading in app + Alembic env.py |
| sentry-sdk[fastapi] | ≥2.0 | Error monitoring for API + worker; no-op until `SENTRY_DSN` is set; `send_default_pii=False`, `include_local_variables=False` |
| slowapi | ≥0.1.9 | Rate limiting (Redis-backed) — signup 10/hour, upload 300/minute, share-resolve 30/minute |
| openpyxl | ≥3.1 | XLSX export from the API process itself (pure-Python, no native deps — promoted from worker-only) |

### Worker extras (installed in worker image only)

| Package | Version | Purpose |
|---|---|---|
| PyMuPDF | ≥1.24 | PDF text-layer extraction + page rasterization (`import fitz`) |
| rapidocr-onnxruntime | ≥1.2.3 | CPU OCR — no system deps, Windows-compatible, pip-only |
| Pillow | ≥10.3 | Image conversion (RGB) + resize for VLM vision mode + thumbnails |
| openai | ≥1.40 | OpenAI-compatible client for vLLM endpoint |
| jsonschema | ≥4.22 | Validates VLM output against doc-type schema |
| python-docx | ≥1.1 | Universal ingestion — `.docx` text extraction |
| openpyxl | ≥3.1 | Universal ingestion — `.xlsx` text extraction |
| python-pptx | ≥1.0 | Universal ingestion — `.pptx` text extraction |
| dateparser | ≥1.2 | Best-effort `document_date` heuristic (plausibility-bounded) |

`.eml` (stdlib `email`) and UBL/MyInvois XML (stdlib `xml.etree.ElementTree`) parsing add **zero new dependencies** — deliberately, per the project's no-native-deps philosophy.

### Frontend

| Package | Version | Purpose |
|---|---|---|
| Next.js | 16.2.7 | React framework (App Router, server components, route groups) |
| React | 19.2.4 | UI library |
| @supabase/supabase-js | ^2.47.0 | Auth session management; token refresh; localStorage persistence |
| lucide-react | ^1.17.0 | SVG icon set |
| tailwind-merge | ^3.6.0 | Merge Tailwind class strings without conflicts |
| clsx | ^2.1.1 | Conditional class name construction |
| class-variance-authority | ^0.7.1 | Component variant API (shadcn/ui pattern) |
| recharts | ^3.8.1 | Chart library (installed, planned for analytics dashboard) |
| date-fns | ^4.4.0 | Date formatting utilities |
| tw-animate-css | ^1.4.0 | CSS animation utilities for Tailwind |
| TypeScript | ^5 | Static typing throughout |

### Infrastructure

| Service | Role |
|---|---|
| Supabase PostgreSQL | Primary database; RLS enforcement; pgcrypto + pg_trgm extensions |
| Supabase Auth | User identity; JWT issuance (HS256); JWKS endpoint for key rotation |
| Supabase Storage | S3-compatible object storage; signed URL issuance |
| Redis (Docker / local) | RQ job queue backend |
| Lightning AI Studio | GPU compute for vLLM server (Qwen3-VL-4B-Instruct) |

---

## 4. Database Schema

### 4.1 Tables Overview

**18 tables total.** Every tenant-owned table has a non-nullable `tenant_id UUID` column and an RLS policy that enforces `tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid`. The `tenants` table is special — its RLS policy uses `id = ...` instead. The live API connects as a dedicated `app_user` Postgres role (`NOBYPASSRLS`) — RLS is genuinely the enforcement layer in production, not just a convenience filter (Alembic still connects as `postgres`, which needs DDL privileges `app_user` doesn't have).

### `tenants`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Python-side `uuid4()` default |
| `name` | VARCHAR NOT NULL | Derived from email domain at first login |
| `plan` | VARCHAR NOT NULL | `"starter"` default; future: `professional / enterprise` |
| `storage_used_bytes` | BIGINT NOT NULL | Incremented on upload; default 0 |
| `storage_limit_bytes` | BIGINT NOT NULL | Default 10 GB (`10 * 1024³`) |
| `llm_monthly_token_cap` | INTEGER nullable | Per-tenant override; NULL = use `settings.llm_monthly_token_cap_default` |
| `trash_retention_days` | INTEGER nullable | Per-tenant override; NULL = use `settings.trash_retention_days_default` (30 days) — trashed documents past this window are auto-purged |
| `trash_last_purged_at` | TIMESTAMPTZ nullable | Rate-limits the auto-purge check (opportunistic, triggered from within a tenant's own request/job — see §6 note under Documents & files) so it runs at most roughly once per check interval, not on every request |
| `created_at` | TIMESTAMPTZ | `server_default=now()` |

### `users`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Equal to Supabase auth `sub` (UUID) |
| `tenant_id` | UUID FK→tenants CASCADE | Indexed |
| `email` | VARCHAR NOT NULL UNIQUE (global) | Matches Supabase Auth's global-per-project identity |
| `name` | VARCHAR NOT NULL | Derived from email username, or invite display name |
| `role` | VARCHAR NOT NULL | `"admin"` or `"user"`; default `"user"` |
| `avatar_initials` | VARCHAR NOT NULL | 1–2 uppercase letters; default `""` |
| `created_at` | TIMESTAMPTZ | |
| `last_login_at` | TIMESTAMPTZ nullable | `NULL` = invite still pending (never logged in); updated on every bootstrap call |

### `documents`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants CASCADE | Indexed |
| `filename` | VARCHAR NOT NULL | Safe display name |
| `original_filename` | VARCHAR NOT NULL | As uploaded by the user |
| `title` | VARCHAR nullable | User-editable; auto-set to `"{vendor} — {invoice_no}"` on deterministic/VLM accept |
| `mime_type` | VARCHAR NOT NULL | Content-sniffed (magic bytes), validated against allow-list |
| `size_bytes` | BIGINT NOT NULL | |
| `storage_key` | VARCHAR NOT NULL | Content-addressed: `"tenants/{tenant_id}/{sha256}"` |
| `checksum` | VARCHAR(64) nullable | sha256, used for dedup |
| `status` | VARCHAR NOT NULL | State machine (see below); default `"queued"` |
| `error_message` | TEXT nullable | Set on `failed`; capped at 2000 chars |
| `document_type` | VARCHAR NOT NULL | Denormalized enum; default `"other"` |
| `document_type_id` | UUID FK→document_types SET NULL | nullable |
| `template_id` | UUID FK→document_templates SET NULL | nullable |
| `layout_fingerprint` | VARCHAR nullable | Reserved for template matching |
| `document_date` | DATE nullable | Best-effort heuristic; plausibility-bounded |
| `page_count` | INTEGER nullable | Set after pipeline |
| `has_text_layer` | BOOLEAN NOT NULL | Default `false` |
| `ocr_used` | BOOLEAN NOT NULL | Default `false` |
| `ocr_confidence` | REAL nullable | Mean per-line OCR score 0.0–1.0; `NULL` for non-OCR sources (scored as a clean 1.0 by the gate) |
| `extracted_data` | JSONB nullable | Structured fields (deterministic or VLM) |
| `extracted_text` | TEXT nullable | Raw text from extraction |
| `confidence` | REAL nullable | Gate/VLM confidence score 0.0–1.0 |
| `vendor` | VARCHAR nullable | Promoted out of `extracted_data` (Level 3) — indexed |
| `invoice_no` | VARCHAR nullable | Promoted out of `extracted_data` (Level 3) |
| `total_amount` | NUMERIC(12,2) nullable | Promoted out of `extracted_data` (Level 3) — indexed |
| `currency` | VARCHAR(8) nullable | Promoted out of `extracted_data` (Level 3) |
| `duplicate_of_document_id` | UUID FK→documents SET NULL | Advisory only — same vendor+invoice_no as another doc; never blocks ingestion |
| `correspondent_id` | UUID FK→correspondents SET NULL | Auto-linked (sender email or match rule) or manually assigned |
| `thumbnail_key` | VARCHAR nullable | Storage key for the generated PNG thumbnail, if any |
| `tags` | VARCHAR[] NOT NULL | **Dead column** — replaced by the `tags`/`document_tags` entity tables; kept only for backward-compat, not written to |
| `search_tsv` | TSVECTOR nullable | FTS index column; built from title + filename + extracted text |
| `deleted_at` | TIMESTAMPTZ nullable | Soft-delete (trash); `NULL` = active |
| `uploaded_by` | UUID FK→users RESTRICT | |
| `uploaded_at` | TIMESTAMPTZ | `server_default=now()` |
| `processed_at` | TIMESTAMPTZ nullable | Set when pipeline finishes (`completed` or `needs_review`) |

**Document status machine:**
```
queued → extracting_text → [ocr_processing] → [ai_extraction] → completed
                                                                → needs_review
                                                                → failed
```
`needs_review` means structured extraction was attempted (the content looked like an invoice/receipt) but neither the deterministic gate nor the VLM accepted it — the document is still fully archived, text-searchable, and downloadable. Any stage can transition to `failed`. The worker re-raises exceptions so RQ records the failure and schedules a retry (max 3 attempts).

### `document_types`
Stores document type definitions. `tenant_id = NULL` means system/global type (seeded in migration 0003) — every tenant sees the full catalog automatically.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants CASCADE nullable | NULL = system type |
| `name` | VARCHAR NOT NULL | e.g. `"invoice"`, `"receipt"` |
| `description` | TEXT nullable | |
| `json_schema` | JSONB nullable | Soft schema for future confidence scoring |
| `is_system` | BOOLEAN NOT NULL | Default `false` |
| `created_at` | TIMESTAMPTZ | |

**Seeded system types (migration 0003):** `invoice`, `receipt`, `contract`, `report`, `letter`, `form`, `other`.

### `document_templates`
Captures learned document layouts for future per-vendor deterministic extraction (self-learning loop seam — not yet driving live extraction decisions).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants CASCADE | |
| `document_type_id` | UUID FK→document_types CASCADE | |
| `name` | VARCHAR NOT NULL | |
| `fingerprint` | VARCHAR NOT NULL | Layout hash |
| `field_mappings` | JSONB NOT NULL | Deterministic extraction rules; default `{}` |
| `status` | VARCHAR NOT NULL | `"candidate"` → `"promoted"` → `"disabled"` |
| `examples_count` | INTEGER NOT NULL | Accepted extractions counter; default 0 |
| `confidence` | REAL nullable | |
| `version` | INTEGER NOT NULL | Default 1 |
| `sample_document_id` | UUID FK→documents SET NULL nullable | |
| `created_at` / `updated_at` | TIMESTAMPTZ | `updated_at` has `onupdate=func.now()` |

### `extractions`
Audit trail for every structured-extraction attempt (deterministic, VLM, or manual). One row per attempt, including failures.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants CASCADE | Indexed |
| `document_id` | UUID FK→documents CASCADE | Indexed |
| `template_id` | UUID FK→document_templates SET NULL nullable | |
| `method` | VARCHAR NOT NULL | `"deterministic"` / `"vlm"` / `"manual"` |
| `model_name` | VARCHAR nullable | e.g. the vLLM model name; `NULL` for deterministic |
| `output` | JSONB nullable | Extracted fields, or `{"_error": ..., "_mode": ...}` on failure |
| `confidence` | REAL nullable | |
| `status` | VARCHAR NOT NULL | `"accepted"` / `"low_confidence"` / `"corrected"` / `"skipped_budget"` |
| `created_at` | TIMESTAMPTZ | |

### `processing_jobs`
One row per document; tracks pipeline execution state.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants CASCADE | Indexed |
| `document_id` | UUID FK→documents CASCADE | Indexed |
| `status` | VARCHAR NOT NULL | `"queued"` / `"running"` / `"completed"` / `"failed"` |
| `stage` | VARCHAR nullable | Current stage: `"text_extraction"` / `"ocr_processing"` / `"deterministic_extraction"` / `"ai_extraction"` |
| `attempts` | INTEGER NOT NULL | Incremented on each RQ execution; default 0 |
| `error` | TEXT nullable | Error message on failure |
| `enqueued_at` | TIMESTAMPTZ | `server_default=now()` |
| `started_at` | TIMESTAMPTZ nullable | |
| `finished_at` | TIMESTAMPTZ nullable | |
| `duration_ms` | INTEGER nullable | Wall-clock processing time |

### `activity_events`
Append-only event log for the dashboard activity feed, per-document History tab, and org-wide Settings audit trail.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants CASCADE | Indexed |
| `type` | VARCHAR NOT NULL | `upload` / `processing_complete` / `processing_failed` / `search` / `download` / `user_added` / `edit` / `trash` / `restore` / `permanent_delete` / `duplicate_detected` / `user_removed` / `role_changed` |
| `document_id` | UUID FK→documents SET NULL nullable | |
| `document_name` | VARCHAR nullable | Denormalized at event time |
| `user_id` | UUID FK→users SET NULL nullable | |
| `user_name` | VARCHAR NOT NULL | Denormalized at event time |
| `timestamp` | TIMESTAMPTZ | `server_default=now()` |
| `meta` | TEXT nullable | Extra context (error excerpt, role change detail, etc.) |

### `api_keys`
Stored for future API key authentication (still not wired to routes).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants CASCADE | Indexed |
| `name` | VARCHAR NOT NULL | Display name |
| `prefix` | VARCHAR NOT NULL | Shown in UI (e.g. `"dw_abc123"`) |
| `hashed_key` | VARCHAR NOT NULL | Never stores raw key |
| `created_at` | TIMESTAMPTZ | |
| `last_used_at` | TIMESTAMPTZ nullable | |

### `ai_usage`
LLM budget-gate ledger (Phase 0) — every VLM call's token cost, so `llm_allowed(tenant_id)` can enforce the monthly cap + the `docs_llm/docs_total ≤ 20%` circuit breaker.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants CASCADE | Indexed |
| `document_id` | UUID FK→documents SET NULL nullable | |
| `model_name` | VARCHAR nullable | |
| `prompt_tokens` / `completion_tokens` / `total_tokens` | INTEGER NOT NULL | Default `0` |
| `created_at` | TIMESTAMPTZ | |

### `tags` + `document_tags` (Phase 4 — Organization)
Real entity tables — **not** the dead `documents.tags` array column above.

`tags`: `id`, `tenant_id` FK, `name` (unique per tenant), `color` (hex, default `#6B7280`), `match` (rule pattern), `matching_algorithm` (`none`/`any`/`all`/`literal`/`regex`), `is_insensitive` (default `true`), `is_inbox_tag` (default `false`), `created_at`.

`document_tags`: `id`, `tenant_id` FK, `document_id` FK, `tag_id` FK — unique on `(document_id, tag_id)`. Assignment is idempotent (`ON CONFLICT DO NOTHING`).

### `correspondents` (Phase 4 / Level 5)
`id`, `tenant_id` FK, `name` (unique per tenant), `email` (nullable, unique per tenant when set — added Level 5, populated by `.eml` sender auto-linking), `match`, `matching_algorithm`, `is_insensitive`, `created_at`.

### `custom_fields` + `document_field_values` (Phase 5 — Metadata)
`custom_fields`: `id`, `tenant_id` FK, `name`, `field_type` (`text`/`number`/`date`/`boolean`/`select`), `options` (JSONB list, for `select`), `position`, `created_at`.

`document_field_values`: `id`, `tenant_id` FK, `document_id` FK, `field_id` FK→custom_fields, `value` (JSONB, nullable).

### `document_type_fields` (added 2026-07-16 — predefined fields per document type)
Links a `custom_fields` catalog entry to one of the 7 fixed document-type strings
(invoice/receipt/contract/report/letter/form/other) as "predefined" for that type — drives the
upload-time field popup and the type-gated custom-field filter on `/documents`. Keyed off the
type **string**, not a `document_types.id` FK — that table's per-tenant/dynamic-type capability
stays dormant until tenant-defined types are built as separate work.

`id`, `tenant_id` FK, `document_type` (one of the 7 fixed strings), `field_id` FK→custom_fields
CASCADE, `required` (BOOLEAN, default `false` — soft-required in the upload popup only, never
enforced by the API), `position`, `created_at`. Unique on `(tenant_id, document_type, field_id)`
— a field can only be predefined once per type.

### `saved_views` (Phase 6 — Retrieval & UX)
`id`, `tenant_id` FK, `name`, `filter_state` (JSONB — the full filter/sort/display config), `is_default`, `created_at`.

### `document_shares` (Level 3 — shareable links)
`id`, `tenant_id` FK, `document_id` FK, `token` (VARCHAR(64), **globally** unique, `secrets.token_urlsafe(32)` — the token itself is the authorization for the one public unauthenticated route), `created_by` FK→users SET NULL, `expires_at` (required, capped 1–30 days at creation), `created_at`.

### 4.2 Indexes (selected — not exhaustive)

| Index | Table | Type | Used for |
|---|---|---|---|
| `ix_documents_search_tsv` | documents | GIN | FTS `@@` operator on `search_tsv` |
| `ix_documents_filename_trgm` | documents | GIN `gin_trgm_ops` | `word_similarity()` fuzzy filename |
| `ix_documents_extracted_gin` | documents | GIN `jsonb_path_ops` | `@>` queries on `extracted_data` |
| `ix_documents_tenant_total_amount` | documents | B-tree | Amount-range filters (Level 3) |
| `ix_documents_tenant_vendor` | documents | B-tree | Vendor filter (Level 3) |
| `ix_documents_tenant_deleted_at` | documents | B-tree | Trash queries |
| `ix_documents_tenant_id` | documents | B-tree | Tenant-scoped list queries |
| `ix_documents_uploaded_by` | documents | B-tree | FK join to users |
| `ix_users_tenant_id` | users | B-tree | |
| `ix_extractions_tenant_id` / `_document_id` | extractions | B-tree | Per-doc audit queries |
| `ix_processing_jobs_tenant_id` / `_document_id` | processing_jobs | B-tree | Job lookup by doc |
| `ix_activity_events_tenant_id` | activity_events | B-tree | Dashboard/audit feed |
| `uq_tags_tenant_name`, `uq_document_tags_doc_tag` | tags, document_tags | unique | Dedup |
| `uq_correspondents_tenant_name`, `uq_correspondents_tenant_email` | correspondents | unique | Dedup (email NULLs don't collide) |
| `uq_document_shares_token` | document_shares | unique | Global token lookup |

### 4.3 Migrations

Current head: **`0016`**. Full list:

| Revision | What it does |
|---|---|
| `0001` | Initial 9 tables + `pgcrypto`/`pg_trgm` extensions + core indexes |
| `0002` | RLS: `ENABLE` + `FORCE ROW LEVEL SECURITY` on every tenant-owned table, one fail-closed policy per table |
| `0003` | Seeds 7 system (`tenant_id=NULL`) document types |
| `0004` | Grants table access to the `authenticated` Postgres role (RLS-enforced, unlike `postgres`/bypassrls) |
| `0005` | Fixes RLS to wrap the GUC read in `NULLIF(..., '')` — Supabase returns `''` not `NULL` when unset |
| `0006` | Adds `ai_usage` table + `tenants.llm_monthly_token_cap` (Phase 0 — LLM budget gate) |
| `0007` | Adds universal-ingestion baseline columns to `documents`: `checksum`, `title`, `document_date`, `thumbnail_key` (Phase 1) |
| `0008` | Adds `documents.deleted_at` + index (Phase 3 — soft-delete/trash) |
| `0009` | Creates `correspondents`, `tags`, `document_tags`, `documents.correspondent_id` (Phase 4 — Organization) |
| `0010` | Creates `custom_fields`, `document_field_values` (Phase 5 — Metadata) |
| `0011` | Creates `saved_views` (Phase 6 — Retrieval & UX) |
| `0012` | Promotes `vendor`/`invoice_no`/`total_amount`/`currency` out of `extracted_data` JSONB into typed columns; adds `duplicate_of_document_id`; backfills historic rows from both live extraction schemas (Level 3) |
| `0013` | Creates `document_shares` — RLS on authenticated CRUD only, the public resolve path bypasses RLS entirely by design (Level 3) |
| `0014` | Adds `correspondents.email` + per-tenant unique constraint (Level 5) |
| `0015` | Creates `document_type_fields`; seeds starter predefined fields for every existing tenant (Invoice: PO Number/Payment Terms; Receipt: Expense Category; Contract: Contract End Date/Renewal Reminder; Report: Department) |
| `0016` | Adds `tenants.trash_retention_days` + `tenants.trash_last_purged_at` (trash auto-retention) |

**How to run migrations:**
```bash
cd backend
alembic upgrade head
```
Uses `ALEMBIC_DATABASE_URL` (direct session connection, port 5432, connects as `postgres` — needs DDL privileges) — not the transaction pooler the live API uses.

---

## 5. Security & Multi-Tenancy

### 5.1 Authentication — JWT Verification

Every authenticated route calls `verify_token(token: str) → TokenData` in `app/core/security.py`.

**Algorithm auto-detection:**
1. Decode the JWT header without verification to read `alg`.
2. **HS256** (Supabase default): verify using `settings.supabase_jwt_secret` (symmetric).
3. **ES256 / RS256** (key rotation): fetch `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` via `PyJWKClient` (module-level singleton, lazy-loaded). Resolve the signing key from the JWT `kid` header.
4. Both paths call `jwt.decode(token, key, algorithms=[alg], audience="authenticated")`.
5. `ExpiredSignatureError` → 401. `InvalidTokenError` → 401. Unsupported algorithm → 401.

**`TokenData` fields extracted from JWT claims:**
| Field | JWT claim | Notes |
|---|---|---|
| `user_id` | `sub` | Supabase user UUID |
| `email` | `email` | |
| `tenant_id` | `app_metadata.tenant_id` | `None` on first login before bootstrap |
| `role` | `app_metadata.role` | `"admin"` or `"user"`; default `"user"` |

### 5.2 First-Login Bootstrap Flow

`POST /api/auth/bootstrap` is called by the frontend immediately after every successful Supabase sign-in.

**When `tenant_id` is absent from the JWT** (first ever login):
1. Creates a `Tenant` row — name derived from email domain (e.g. `"gmail"` from `user@gmail.com`, title-cased as `"Gmail"`).
2. Seeds 4 starter tags and the same starter **predefined custom fields** migration 0015 backfilled for pre-existing tenants (PO Number/Payment Terms on Invoice, Expense Category on Receipt, Contract End Date/Renewal Reminder on Contract, Department on Report) — mirrored in code, not read from the old migration, so every tenant created via normal signup gets the same onboarding value instead of an empty Custom Fields page.
3. Calls `supabase_admin().auth.admin.update_user_by_id(user_id, {"app_metadata": {"tenant_id": "...", "role": "admin"}})` → patches the Supabase user record so all future JWTs carry the tenant.
4. Creates a `User` row with `role="admin"`.
5. Subsequent logins hit the idempotent path: upserts user, updates `last_login_at`, syncs role.

**Why a dedicated bootstrap call?**
Supabase JWTs are issued before the backend user/tenant rows exist. Bootstrap is the bridge: it creates the rows, patches the Supabase metadata, and makes the system self-configuring on first login with zero admin setup.

### 5.3 Multi-Tenancy via PostgreSQL RLS

Every authenticated API route goes through `get_tenant_db` in `app/core/deps.py`:

```python
db.begin()
db.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
# true = transaction-local: GUC resets automatically at commit/rollback
```

**RLS policy (migration 0005):**
```sql
USING (
  tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
)
WITH CHECK (
  tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
)
```

**Guarantees:**
- `SELECT`: returns only rows belonging to the current tenant.
- `INSERT` / `UPDATE`: rejected if `tenant_id` does not match the GUC (`WITH CHECK` fails).
- No GUC set (empty string): `NULLIF(..., '')` returns `NULL`; `NULL::uuid` fails the equality; **0 rows returned** — fail-closed.
- The application never needs to write `WHERE tenant_id = ?` as the primary isolation mechanism; RLS is the enforcement layer. App-level filters are conveniences only.

**Worker sessions** use `tenant_session(tenant_id)` from `app/core/tenant_context.py` — same mechanism: begins a transaction, sets the GUC, enforces RLS identically to the API path.

### 5.4 Storage Security

- Files are stored **content-addressed**: `tenants/{tenant_id}/{sha256}` in Supabase Storage — `unique(tenant_id, sha256)` gives free dedup (re-uploading identical bytes reuses the row).
- The API **never streams file bytes** in HTTP responses. It issues signed URLs via `storage.create_signed_url(key, expires_in=300)` (5-minute TTL) for downloads and thumbnails, and for the one public share-resolve route.
- Download route: verifies the document belongs to the tenant (RLS-checked `db.get`), then calls the storage adapter for a signed URL.
- Worker downloads files using the service role key — only the worker runs with elevated privileges, never the public API.

### 5.5 Input Validation

- **File MIME type**: content-sniffed by magic bytes (never the client-declared content-type or filename extension) against an explicit allow-list — PDF, images, Office (DOCX/XLSX/PPTX via zip-peek), text/CSV/Markdown, email (`.eml`, detected by RFC822 header heuristic), and XML (detected by the `<?xml` declaration, with a UBL/MyInvois-specific sub-check). Unknown types → HTTP 415.
- **File size**: checked against `settings.max_upload_mb` → HTTP 413. **Batch count**: capped per upload request (rejects with 413 before any file I/O).
- **Rate limiting**: `slowapi`, Redis-backed — signup 10/hour/IP, upload 300/minute/IP, public share-resolve 30/minute/IP.
- **CORS**: origins validated against `settings.cors_origins_list` (comma-separated from `CORS_ALLOW_ORIGINS`).
- **XXE guard**: XML parsing (UBL/MyInvois) rejects any document declaring a `DOCTYPE`/`ENTITY` before ever handing it to `xml.etree.ElementTree` — legitimate e-invoices never declare one.
- **All SQL**: parameterized via SQLAlchemy `func.*` or `text(..., {"param": value})` — no raw string interpolation.

### 5.6 Error Monitoring & LLM Budget

- **Sentry** (`app/core/monitoring.py::init_sentry`): wired in both `main.py` and `worker.py`, no-op unless `SENTRY_DSN` is set. Explicitly `send_default_pii=False` and `include_local_variables=False` — the latter defaults to `True` in sentry-sdk and would otherwise leak document text from crash stack frames (a real PDPA risk, not a hypothetical one).
- **LLM budget gate** (`app/core/ai_budget.py`, backed by the `ai_usage` table + `tenants.llm_monthly_token_cap`): `llm_allowed(db, tenant_id)` enforces a per-tenant monthly token cap and a `docs_llm/docs_total ≤ 20%` circuit breaker. If the budget is exhausted, the document is marked `needs_review` instead — the pipeline never blocks on the LLM being unavailable.
- **Non-bypassrls DB role**: the live API connects as `app_user` (`NOBYPASSRLS`), not the Supabase `postgres` superuser — RLS is the real enforcement layer for every live request, not just a defense-in-depth convenience.

### 5.7 Security Hardening (added 2026-07-22)

- **Security headers on every API response** (`core/security_headers.py`): `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Cross-Origin-Opener-Policy`, `Permissions-Policy`, and a locked-down `Content-Security-Policy: default-src 'none'` (the API only ever returns JSON, so nothing needs to be allowed). Swagger/ReDoc routes are exempted from the CSP so their CDN assets keep working in dev. `Strict-Transport-Security` only fires when `ENV=production`. The frontend (`next.config.ts`) sets the equivalent headers on every page.
- **API docs gated off in production** — `/api/docs`, `/api/redoc`, `/api/openapi.json` are disabled when `ENV=production` so the schema isn't publicly enumerable; unchanged in dev.
- **Production error hygiene** — a catch-all exception handler, active only when `ENV=production`, returns a generic JSON 500 instead of a stack trace, while still calling `sentry_sdk.capture_exception` so the real error is tracked. Dev keeps FastAPI's normal verbose behavior untouched.
- **Global rate-limit fallback** — `default_limits=["200/minute"]` per IP on top of the existing stricter per-endpoint limits (signup 10/hr, upload 300/min, share-resolve 30/min). Uses `swallow_errors=True` so a Redis outage fails **open** (the check is skipped, not a 500) — consistent with the project's degrade-gracefully rule, since this ceiling now touches every route, not just the ones that already depended on Redis.
- **Input validation tightening** (`core/validation.py`) — a lightweight regex email validator (not pydantic's `EmailStr`, to avoid a new dependency) on signup/invite/correspondent-email fields; explicit `max_length` bounds on free-text inputs (org name, tag/correspondent name + match pattern, custom-field name, document title) and on custom-field values.
- **Stored-XSS fix in search** (`search/query.py`/`search/service.py`) — the FTS snippet used to insert `<mark>` tags directly around matched terms inside `ts_headline()` output, then rendered via `dangerouslySetInnerHTML` on the frontend, without ever escaping the surrounding document text. A document containing something like `<img src=x onerror=...>` in its extracted text would have executed that script in a viewer's browser the moment it appeared in their own search results. Fixed by having Postgres wrap matches in sentinel control characters (`\x01`/`\x02`, illegal in real text) instead of literal tags; `snippet_html_safe()` then HTML-escapes the entire string and only afterward swaps the escape-proof sentinels for real `<mark>` tags — so nothing from the source document can inject markup, but highlighting still works.
- **Dependency scanning** — `pip-audit` added as a backend dev dependency; run before releases.

---

## 6. Backend API — All Endpoints

Base URL: `http://localhost:8000/api` (dev — canonical port **8000**). All authenticated routes require `Authorization: Bearer <JWT>`; the two exceptions are noted explicitly below.

All response bodies use **camelCase** field names (via `CamelModel` alias generator). All `id` fields are UUID strings. 12 routers, all mounted under `/api`.

**Auth & team accounts** (`/api/auth/*`)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/auth/signup` | None, rate-limited 10/hr | Pre-confirmed account creation (local testing) |
| `POST` | `/auth/bootstrap` | JWT (no tenant) | Idempotent first-login tenant+user creation; seeds 4 starter tags for a brand-new tenant |
| `GET` | `/auth/me` | JWT (no tenant) | Current user + tenant (same idempotent upsert as bootstrap) |
| `PATCH` | `/auth/tenant` | Admin | Rename the organisation |
| `GET` | `/auth/users` | JWT + tenant | List all members of the tenant |
| `POST` | `/auth/users/invite` | Admin | Invite a teammate by email (Supabase Auth admin invite) |
| `PATCH` | `/auth/users/{id}/role` | Admin | Change a teammate's role (refuses to demote the last admin) |
| `DELETE` | `/auth/users/{id}` | Admin | Remove a teammate (refuses self-removal / last admin) |

**Documents & files** (`/api/documents/*`, `/api/activity`)
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/documents` | Upload one or more files (rate-limited 300/min); batch-count capped |
| `GET` | `/documents` | List with filters: status, type, tag, correspondent, date range, amount range, vendor, inbox, q, sort, page, trashed |
| `GET` | `/documents/{id}` | Fetch one document |
| `GET` | `/documents/{id}/download` | `{"url": "<signed-url>"}`, 5-min TTL; logs a `download` activity event |
| `GET` | `/documents/{id}/preview` | Same signed-URL shape, for inline viewing — does **not** log a download event, so merely opening the detail page no longer pollutes the audit trail |
| `GET` | `/documents/{id}/thumbnail` | Signed thumbnail URL; 404 if none generated |
| `PATCH` | `/documents/{id}` | Edit title / type / date / correspondent / extracted-data patch |
| `POST` | `/documents/{id}/retry` | Re-enqueue a failed document |
| `POST` | `/documents/{id}/extract` | Re-run VLM extraction only (doc stays completed) |
| `POST` | `/documents/extract-missing` | Bulk-enqueue VLM extraction for completed docs with no structured data |
| `DELETE` | `/documents/{id}` | Soft-delete (move to trash) |
| `POST` | `/documents/{id}/restore` | Restore from trash |
| `DELETE` | `/documents/{id}/permanent` | Permanently delete one trashed document |
| `POST` | `/documents/empty-trash` | Permanently delete every trashed document |
| `POST` | `/documents/bulk-trash` | Soft-delete multiple documents |
| `POST` | `/documents/bulk-tag` | Assign/remove a tag on multiple documents |
| `POST` | `/documents/bulk-set-type` | Set document type on multiple documents |
| `GET` | `/activity` | Paginated audit-trail feed (org-wide, or `?document_id=` scoped) |

**Trash auto-retention** (added 2026-07-23): trashed documents past `tenants.trash_retention_days`
(or the global `TRASH_RETENTION_DAYS_DEFAULT` when unset) are purged automatically —
`app/modules/files/retention.py::maybe_purge_expired_trash`. There's deliberately no global RQ
cron job for this: the `tenants` table's own RLS policy means there is no way to enumerate every
tenant from a normal (non-bypassrls) session, so a global sweep would need to bypass RLS — banned
by this project's hard tenancy rule. Instead the check is **opportunistic**: it runs inside an
already-open, tenant-scoped session at two points that happen naturally in the course of normal
use — listing the trash view (`GET /documents?trashed=true`) and the start of every document's
worker processing job — rate-limited via `trash_last_purged_at` so it does real work at most
about once per check interval, not on every call. When it purges documents, it records one
summary `ActivityEvent` (`user_name="system"`) rather than one per document, so there's an audit
trail for something that happens with nobody watching.

**Dashboard & search**
| Method | Path | Purpose |
|---|---|---|
| `GET` | `/dashboard` | Stats + recent docs + activity feed |
| `GET` | `/search` | Full-text + fuzzy search (`q`, `type`, `date`, `status`, `page`) |

**Tags & correspondents** (`/api/tags/*`, `/api/correspondents/*`)
| Method | Path | Purpose |
|---|---|---|
| `GET`/`POST` | `/tags` | List / create tags |
| `PATCH`/`DELETE` | `/tags/{id}` | Update / delete a tag |
| `POST`/`DELETE` | `/documents/{id}/tags/{tag_id}` | Assign / remove a tag (idempotent both ways) |
| `POST` | `/tags/apply-rules` | Retroactively apply tag/correspondent match rules to already-ingested docs (paginated, oldest-first) |
| `GET`/`POST` | `/correspondents` | List / create correspondents |
| `PATCH`/`DELETE` | `/correspondents/{id}` | Update / delete a correspondent |

**Metadata & saved views** (`/api/custom-fields/*`, `/api/saved-views/*`, `/api/document-type-fields`)
| Method | Path | Purpose |
|---|---|---|
| `GET`/`POST` | `/custom-fields` | List / create custom field definitions |
| `PATCH`/`DELETE` | `/custom-fields/{id}` | Update / delete a definition (+ its values) |
| `POST`/`DELETE` | `/documents/{id}/fields/{field_id}` | Set / clear a custom field value on a document |
| `GET` | `/document-type-fields` | List all predefined-field links, grouped by document type |
| `POST`/`PATCH`/`DELETE` | `/document-types/{type}/fields` | Attach / update / detach a predefined field for one document type |
| `GET`/`POST` | `/saved-views` | List / create saved views |
| `PATCH`/`DELETE` | `/saved-views/{id}` | Update / delete a saved view |

`GET /documents` and `GET /documents/export` additionally accept `custom_field_id` +
`custom_field_value` (exact match for select/boolean fields, partial `ILIKE` for text) or
`custom_field_min`/`custom_field_max`/`custom_field_date_from`/`custom_field_date_to` (number/date
fields) — the field's type is always resolved server-side, never trusted from the client, so a
select field can't be over-matched with a substring search.

**Export & sharing** (`/api/documents/export`, `/api/*share*`)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/documents/export` | Tenant | CSV or XLSX export of filtered documents (5,000-row soft cap, flagged not silent) |
| `POST` | `/documents/bulk-download` | Tenant | Zip of selected originals (100-file cap) |
| `POST` | `/documents/{id}/share` | Tenant | Create a time-limited public share link (1–30 days) |
| `GET` | `/documents/{id}/shares` | Tenant | List share links for a document |
| `DELETE` | `/shares/{id}` | Tenant | Revoke a share link |
| `GET` | `/share/{token}` | **None** — public, rate-limited 30/min | Resolve a token to a signed download URL (404/410 if invalid/expired/revoked) |

**Misc**
| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/health` | None | Liveness check |

`backend/app/modules/templates/` and `backend/app/modules/types/` exist as directories but are empty stubs (`__init__.py` only) — no HTTP surface. Document types are seeded data read directly off the model; templates are managed entirely inside the IDP pipeline.

### Upload — `POST /api/documents`

**Request:** `multipart/form-data`
- `files`: one or more files (`UploadFile[]`)
- `document_type`: optional repeated string field; index-matched to files; defaults to `"other"`
- `field_values`: optional repeated JSON string `{field_id: value}` — values for that type's
  predefined custom fields, captured at upload time
- `new_fields`: optional repeated JSON string `[{name, fieldType, options, value}]` — define a
  brand-new custom field inline and auto-attach it as predefined for that file's type
- `attach_fields`: optional repeated JSON string `[{fieldId, value}]` — reuse an already-existing
  catalog field (from another document type) as predefined for this one

All three are best-effort: any parse/validation failure on a field value is logged and skipped,
never raised — a bad custom-field value can never block the document itself from archiving.

**Response:** `DocumentListOut`
```json
{
  "items": [{ "id": "...", "status": "queued", "filename": "invoice.pdf", ... }],
  "total": 1, "page": 1, "pageSize": 20
}
```

### Search — `GET /api/search`

**Query parameters:**
| Param | Type | Notes |
|---|---|---|
| `q` | string | Search terms. Empty → empty result |
| `type` | string | Filter by `document_type` |
| `date` | string | `"today"/"week"/"month"/"any"` — filters by `uploaded_at` |
| `status` | string | Filter by document status |
| `page` | int | Default 1; page size 20 |

**Response:** `SearchListOut`
```json
{
  "items": [{
    "document": { ...DocumentOut },
    "score": 0.87,
    "snippet": "...paid <mark>INVOICE</mark> total...",
    "matchedFields": ["content", "filename"]
  }],
  "total": 5, "page": 1, "pageSize": 20
}
```

---

## 7. IDP Pipeline — Tier by Tier

The pipeline runs in the RQ worker process (`python -m app.worker`). Entrypoint: `app/modules/idp/jobs.py :: process_document(doc_id, tenant_id)`. It is a **deterministic-first cost cascade** — each tier runs only when the cheaper one couldn't finish the job, and the VLM (Tier 4) is a true exception handler, not a stage every document passes through.

```
Tier 0  Parse (free)              — PyMuPDF / Office parsers / text / email / UBL-XML
Tier 1  OCR (cheap, CPU)          — RapidOCR, only when no usable text layer exists
Tier 2  Deterministic extraction  — regex/keyword rules (or direct XML parse for UBL)
        + quality gate (0.75)     — score ≥ 0.75 → accepted, done, no AI involved
Tier 4  VLM fallback              — ONLY on gate-fail, target 10–20% of candidates
```

(There is no "Tier 3" in the live pipeline yet — layout/table models like TATR/docling are an approved-but-unbuilt future tier, reserved in the numbering.)

### Tier 0 — Universal Parsing (`app/modules/idp/pipeline.py::run_extraction`, dispatched by MIME type)

A file-type dispatch table, not a single code path — every format gets a small dedicated parser, all returning the same `ExtractionResult(text, page_count, has_text_layer, ocr_used, ocr_confidence)` shape:

| MIME family | Parser | Notes |
|---|---|---|
| `application/pdf` | `parsing.py` (PyMuPDF) | Text layer if usable, else rasterize → OCR (Tier 1) |
| Images (PNG/JPEG/WEBP/TIFF) | `ocr.py` (RapidOCR) | Always OCR — no text layer to check |
| DOCX/XLSX/PPTX | `office_parsing.py` | `python-docx` / `openpyxl` / `python-pptx`, direct text extraction |
| TXT/CSV/Markdown | `office_parsing.py::extract_plain_text` | UTF-8 decode, Latin-1 fallback |
| `.eml` (email) | `office_parsing.py::extract_email_text` | Headers (From/To/Cc/Subject/Date) + body (prefers text/plain, strips HTML fallback); `parse_sender_from_text` separately extracts a structured `(name, email)` from the From: header for correspondent auto-linking |
| XML (UBL/MyInvois e-invoice) | `ubl_invoice.py` | See below — the one format that skips Tier 2's regex entirely |
| Anything else | — | `ValueError: Unsupported mime type` — MIME sniffing (`mimetype.py`) is content-based (magic bytes / `<?xml` prolog), never trusts the client-declared type or filename extension |

**MyInvois/UBL-XML is a special case worth calling out**: `idp/ubl_invoice.py` parses the UBL 2.1 Invoice XML tree directly into an `ExtractionCandidate` (vendor, invoice number, dates, total, line items) — the source data is already structured, so there's nothing for regex to do. It still runs through the exact same Tier 2 quality gate as every other deterministic source (with `ocr_confidence=None`, scored as a clean 1.0), and it **never** falls through to the VLM on gate-fail (there's no page image to send a vision model) — a malformed e-invoice goes straight to `needs_review`. Uses stdlib `xml.etree.ElementTree` only; rejects any `DOCTYPE`/`ENTITY` declaration before parsing (XXE guard).

**PDF text-layer detection (`parsing.py`):**
```
file_bytes
  → fitz.open(stream=bytes) → extract_text_layer(doc) → raw_text
  → has_usable_text_layer(text, page_count)?
        threshold: non-whitespace chars ≥ max(16, 8 × page_count)
  → YES → ExtractionResult(has_text_layer=True, ocr_used=False)   [FREE PATH]
  → NO  → rasterize_page(page, dpi=200) per page → OCR each (Tier 1)
```

### Tier 1 — OCR (`app/modules/idp/ocr.py`)

Used when no usable text layer exists (scanned PDF pages), or for image files.

```
png_bytes
  → PIL.Image.open() → convert("RGB") → numpy.array(image)
  → RapidOCR()(array) → list of [box, text, score]
  → join lines with "\n"; mean score across lines
  → return (text: str, confidence: float)
```

`RapidOCR` engine is a **process-level singleton**, initialized on first call (~1–2s to load the ONNX model; fast afterward).

### Tier 2 — Deterministic Extraction + Quality Gate (`app/modules/idp/extract.py` + `gate.py`)

Only runs for documents whose MIME is structured-extraction-eligible (PDF, image, or UBL-XML) **and** whose text passes a keyword gate (`detect_candidate_type` — looks for invoice/receipt language: "tax invoice", "invoice no", "bill to", "receipt", etc.). Contracts, reports, letters, and everything else never reach this tier at all — they get the full universal baseline (text/thumbnail/metadata/search) and stop there.

`extract_candidate(text) -> ExtractionCandidate | None` — regex + `dateparser`, no ML:
- Vendor: heuristic line-scan (skips label lines ending in `:`)
- Invoice number: `(?:invoice|inv|receipt)\s*(?:no\.?|number|#)...`
- Amounts: currency-coded (`MYR`/`USD`/`SGD`/...) or symbol (`$`/`€`/`£`) or bare `RM` (word-boundary checked, not a substring match)
- Total: most-authoritative label wins (`balance due` > `grand total` > `amount due` > `total amount` > bare `total`, explicitly not `subtotal`)
- Dates: `due date` label vs bare `date` (won't match inside "due date")
- Line items: qty/unit-price/amount row patterns, skips lines that are themselves total labels

`gate.score_extraction(candidate, ocr_confidence) -> GateResult` — weighted score, **pass threshold 0.75** (changing this needs explicit human sign-off, never tuned to force a specific document through):

| Component | Weight | What it checks |
|---|---|---|
| Completeness | 0.4 | invoice_number + (invoice_date or due_date) + total_amount present; +0.1 bonus for vendor |
| Format validity | 0.2 | invoice number has a digit; total > 0; due_date ≥ invoice_date |
| OCR confidence | 0.2 | The document's OCR score; `None` (no OCR involved — text-layer PDF, or UBL-XML) scores a clean **1.0**, not a penalty |
| Math audit | 0.2 | `sum(line_items.amount)` reconciles with `total_amount` within 2% (or $1); neutral 1.0 if no line items to check |

**Score ≥ 0.75 → accepted** (`doc.extracted_data`, `doc.confidence`, typed columns all set, `deterministic_accepted = True`) — no AI involved, this is the ~85-90% path. Below 0.75 → falls through to Tier 4.

### Tier 4 — VLM Fallback (`app/modules/idp/extraction.py`) — the exception handler

Runs **only** when Tier 2 was attempted and failed the gate, **and** the MIME type is VLM-eligible (PDF or image — UBL-XML explicitly never reaches this tier, see above), **and** the tenant's LLM budget allows it (`ai_budget.llm_allowed`). Every VLM call records token usage in `ai_usage` and an `Extraction(method="vlm")` row regardless of outcome.

#### Token Budget Math (config-driven)
```
vlm_max_model_len     = 2048   (total context window: input + output)
vlm_max_output_tokens = 768    (tokens reserved for model's JSON response)
prompt_overhead       = 200    (system prompt + user message wrapper)
safety_margin         = 50

input_budget = max(256, 2048 − 768 − 200 − 50) = 1030 tokens
```
All these values adjust automatically when you change `.env` settings.

#### Text Mode (digital PDF — has_text_layer = True)

Runs `_extract_two_phase(text, client)` — two calls to fit within the output-token budget:

**Phase 1 — Header extraction** (1 call): vendor, invoice_number, invoice_date, total_amount, currency, buyer, buyer_address, vendor_address, gst, grand_total, terms_conditions. `line_items` explicitly prohibited/stripped from this phase's output.

**Phase 2 — Line items extraction** (up to `vlm_max_chunk_calls − 1` calls, one per text chunk): every product/service row, `{"code", "description", "qty", "unit_price", "amount"}` each.

#### Vision Mode (scanned / image — has_text_layer = False)

```
file_bytes + mime_type
  → render_page_images(max_pages=10, dpi=120) → resize (max_side=512) → base64
  → batch 2 images per call → chat.completions.create(..., temperature=0)
  → _tolerant_parse each response → _merge_extractions(parts)
```

#### Output Repair — `_tolerant_parse(text)`

The output-token limit can truncate the model's JSON mid-value. Four fallback layers: strip code fences → `json.loads` → find the outermost `{...}` span → `_repair_truncated_json` (stack-based bracket tracker: closes open strings, strips trailing commas, removes dangling truncated keys, closes remaining brackets in reverse order).

#### Merge — `_merge_extractions(parts)`

| Field type | Merge strategy |
|---|---|
| `documentType` | Majority vote among non-`"other"` values |
| `confidence` | Arithmetic mean across all parts |
| List fields (`line_items`) | Concatenated in call order |
| Scalar fields (`vendor`) | First non-empty value wins |
| Total-like keys | Last non-empty value wins (grand total is typically on the final page) |

VLM output is **re-gated** through the same acceptance logic as Tier 2 (confidence ≥ `settings.confidence_threshold`). Still failing → `needs_review`, never `failed` — the document stays fully archived and searchable regardless of extraction outcome.

### Post-extraction (every document, regardless of which tier accepted it)

- Thumbnail generation (PDF first page / image resize; `None` for everything else — swallows all exceptions)
- `search_tsv` built from `title + original_filename + extracted_text` (rebuilt on title edit too, so renamed docs stay searchable)
- `document_date` guess (`dateparser`, plausibility-bounded: rejects >3 days future or >50 years past)
- Auto-tag + auto-correspondent-link (`tags/matching.py::run_document_matching`) — for `.eml` docs, tries the parsed sender email first (get-or-create a correspondent), falls back to free-text/vendor-name rules; wrapped in try/except so a bad rule never blocks the document
- Auto-title (`"{vendor} — {invoice_no}"`) + duplicate-invoice detection (same vendor+invoice_no as another non-trashed doc — advisory only, sets `duplicate_of_document_id`, never blocks) — both only on first-time processing, never on manual re-extraction

### Error Handling in the Worker

| Scenario | Behaviour |
|---|---|
| Document not found on startup | `LookupError` raised → RQ retries (upload→commit race condition) |
| Text extraction crash | Sets `status=failed`, logs error, re-raises → RQ retry (max 3) |
| Deterministic candidate found but gate fails, VLM not eligible/budget exhausted | `needs_review` — document completes, fully searchable, no `extracted_data` |
| VLM crash / timeout / no data | Logs warning, inserts `Extraction` row with `_error` field, falls to `needs_review` (document is still text-searchable) |
| Max retries exceeded | `status=failed`, `error_message` stored, `ActivityEvent(processing_failed)` logged |

---

## 8. Search System

**Two deliberately different surfaces**, not one: `GET /api/search` is the freetext-ranked tier described below (title/content/filename relevance, snippets); `GET /api/documents` is the structured-filter tier (status, type, tag, correspondent, date range, **amount range, vendor** — Level 3, custom fields, saved views). Unifying them was explicitly scoped out — they serve different UI surfaces (the dedicated Search page vs. the Documents list's filter bar) and merging them wasn't needed to deliver either one well.

Freetext search is a three-tier query — all executed in a single SQL statement, no extra services. Trashed documents (`deleted_at IS NOT NULL`) are excluded from both surfaces.

### Tier 1 — Full-Text Search (exact match + phrases)

```python
tsquery = func.websearch_to_tsquery("english", q)
content_match = Document.search_tsv.op("@@")(tsquery)
```

`websearch_to_tsquery` accepts natural language: `"apple OR banana"`, `"total amount" -gst`, quoted phrases. English stemming applied (`invoice` matches `invoices`, `invoiced`).

### Tier 2 — Prefix Full-Text Search (partial words)

```python
prefix_str = " & ".join(f"{tok}:*" for tok in tokens if len(tok) >= 2)
prefix_tsquery = func.to_tsquery("english", prefix_str)
content_match = content_match | Document.search_tsv.op("@@")(prefix_tsquery)
```

`"inv"` → `to_tsquery('english', 'inv:*')` → matches `invoice`, `inventory`, `invoice_number`. Used for live-as-you-type searching.

### Tier 3 — Trigram Filename/Title Matching (typo tolerance)

```python
filename_match = func.greatest(
    func.extensions.word_similarity(q.lower(), func.lower(Document.title)),
    func.extensions.word_similarity(q.lower(), func.lower(Document.original_filename)),
) >= 0.2
```

`pg_trgm` extension (installed in Supabase's `extensions` schema — the live API connects as `app_user`, whose `search_path` doesn't include it by default, so the function call is schema-qualified; an earlier regression that used the unqualified name broke *all* search, not just fuzzy matches, since one bad clause poisoned the whole `WHERE`). `word_similarity` measures overlap of character 3-grams; `0.2` catches common typos (`"invioce"` matches `"invoice_2024.pdf"`). Matches against **both** `title` and `original_filename` (via `greatest()`) so a renamed document stays findable under its new title without losing its original-filename match — `search_tsv` is rebuilt on title edit for the same reason.

### Ranking & Snippet

```python
rank = (
    func.coalesce(func.ts_rank_cd(Document.search_tsv, tsquery), 0.0)
    + func.coalesce(func.extensions.word_similarity(q.lower(), func.lower(Document.original_filename)), 0.0)
)

snippet = case(
    (content_match, func.ts_headline("english", Document.extracted_text, headline_tsquery,
        "StartSel=<mark>,StopSel=</mark>,MaxFragments=2,MinWords=5,MaxWords=24,ShortWord=2")),
    else_=None
)
```

`ts_headline` returns a short excerpt with matching terms wrapped in `<mark>` tags. The frontend renders this with `dangerouslySetInnerHTML` — the `<mark>` elements are highlighted via CSS.

### Complete Query Flow

```sql
SELECT documents.*, rank AS score, snippet, content_match, filename_match
FROM documents
WHERE (content_match OR filename_match)
  AND deleted_at IS NULL                                        -- trash excluded
  AND tenant_id = current_setting('app.current_tenant')::uuid   -- via RLS
  [AND document_type = ?]
  [AND status = ?]
  [AND uploaded_at >= ?]
ORDER BY score DESC, uploaded_at DESC
LIMIT 20 OFFSET ((page-1) * 20)
```

Tenant isolation is enforced by RLS — no explicit `WHERE tenant_id` needed in application code.

---

## 9. Queue & Worker

### Worker Entry Point

```bash
cd backend
python -m app.worker
```

`app/worker.py` branches on platform:
- **Windows**: `rq.SimpleWorker` (no `os.fork` — Windows doesn't support it)
- **Linux/other**: `rq.Worker(with_scheduler=True)` (supports `job.retry()` scheduling)

Listens on queue: `settings.idp_queue_name` (default: `"idp"`).

### Job Functions (`app/modules/idp/jobs.py`)

**`process_document(doc_id, tenant_id)`** — full pipeline, called on every new upload.
- Retry policy: `Retry(max=3, interval=[10, 30, 60])` seconds between attempts.
- Re-raises on outer exception so RQ records the failure.

**`ai_extract_document(doc_id, tenant_id)`** — VLM-only re-extraction, called by `/extract` and `/extract-missing`.
- Retry policy: `Retry(max=2, interval=[15, 60])` seconds.
- Does NOT re-raise — document stays `completed` regardless of VLM outcome.

### Job Idempotency

Both job functions are safe to retry:
- `process_document` checks for document existence before starting; `LookupError` on not-found triggers a retry.
- `ai_extract_document` skips documents that have no `extracted_text` and are not `completed`.
- All DB writes inside `tenant_session` are wrapped in a transaction; a crash before commit leaves no partial state.

---

## 10. Frontend

### 10.1 Project Structure

```
frontend/
├── app/
│   ├── page.tsx                    # redirect to /login
│   ├── layout.tsx                  # root layout (fonts, title, PWA manifest/icons)
│   ├── manifest.ts                 # PWA web manifest (Next.js file convention)
│   ├── login/page.tsx              # login form + forgot-password
│   ├── signup/page.tsx             # self-serve signup
│   ├── accept-invite/page.tsx      # Supabase invite-email landing page (public)
│   ├── reset-password/page.tsx     # Supabase password-recovery landing page (public)
│   ├── shared/[token]/page.tsx     # public document-share resolver (public)
│   └── (app)/                      # authenticated route group
│       ├── layout.tsx              # wraps pages in AuthProvider + Sidebar
│       ├── dashboard/page.tsx
│       ├── upload/page.tsx
│       ├── documents/page.tsx
│       ├── documents/[id]/page.tsx
│       ├── search/page.tsx
│       ├── tags/page.tsx
│       ├── correspondents/page.tsx
│       ├── custom-fields/page.tsx
│       ├── views/page.tsx
│       └── settings/page.tsx
├── components/
│   ├── sidebar.tsx                 # navigation + storage meter + user row
│   ├── status-badge.tsx            # coloured pill for document status
│   └── activity-item.tsx           # shared ActivityIcon/ActivityLabel for every ACT_* type
├── lib/
│   ├── api.ts                      # all API calls (typed, authenticated)
│   ├── auth.tsx                    # AuthProvider + useAuth() context
│   ├── supabase.ts                 # Supabase client singleton
│   ├── format.ts                   # formatBytes(), formatRelativeTime()
│   └── utils.ts                    # cn() (clsx + tailwind-merge)
├── public/
│   ├── icon-192.png / icon-512.png # PWA icons
│   └── ... (default Next.js SVGs)
└── types/
    └── index.ts                    # all TypeScript types
```

`lib/mock-data.ts` no longer exists — deleted once Settings was wired to real data.

### 10.2 Auth Flow

**Login** (`/login/page.tsx`):
```
1. supabase.auth.signInWithPassword({ email, password })
2. apiBootstrap()   →  POST /api/auth/bootstrap  (creates/upserts backend user + tenant)
3. router.push("/dashboard")
```

**Session guard** (`lib/auth.tsx` — `AuthProvider`):
- Wraps all `(app)/*` routes.
- On mount: `supabase.auth.getSession()` → no session → redirect to `/login`.
- Has session: `apiMe()` → populates `user` and `tenant` state.
- Subscribes to `supabase.auth.onAuthStateChange`: `SIGNED_OUT` event → clear state + redirect.
- While `loading=true`: renders a full-screen spinner.

**Token flow:**
Every `lib/api.ts` function calls `authHeaders()` which calls `supabase.auth.getSession()` at call time. The Supabase SDK handles token refresh transparently. No explicit token expiry logic in the app code.

**Sign-out:**
`signOut()` → `supabase.auth.signOut()` → `onAuthStateChange` fires `SIGNED_OUT` → redirect to `/login`.

### 10.3 Pages

#### `/dashboard`
- Calls `apiDashboard()` on mount.
- Renders: KPI cards (Total Documents, Processed, In Pipeline, Failed), Recent Documents table, Storage Usage progress bar (`storageUsedBytes / storageLimitBytes`), Activity feed with relative timestamps.

#### `/upload`
- Drag-and-drop zone (HTML5 drag events) + file input fallback, plus a dedicated **"Take a photo"** button (`capture="environment"`) for mobile camera capture, alongside the regular file picker.
- Accepts PDF, scans, images, Word/Excel/PowerPoint, text/CSV/Markdown, email (`.eml`), and e-invoice XML (UBL/MyInvois).
- Default document type selector (pill buttons): invoice, receipt, contract, report, letter, form, other.
- Per-file type override `<select>`. Batch upload capped server-side; per-file size capped at `MAX_UPLOAD_MB`.
- On submit: sequential `apiUploadDocument(formData)` per file; per-file status indicator, duplicate detection surfaced (identical sha256 already archived).
- After success: `router.push("/documents")`.

#### `/documents`
- Calls `apiDocuments({ status, type, tag, correspondent, dateFrom, dateTo, amountMin, amountMax, vendor, inbox, sort, q, page, trashed })` on mount and on filter change. The vendor/min-amount/max-amount inputs live directly in the filter bar (not hidden behind saved views).
- Filter state also seeds itself from the URL's own query string on navigation (`useSearchParams`, wrapped in a `Suspense` boundary per Next 16's requirement) — so the sidebar's Inbox link and a saved view's "open" link actually apply their filters instead of landing on an unfiltered list.
- Grid and table view toggle; pagination; sort options.
- **Polling** while any row is in a non-terminal status. Cleared once all visible rows reach a terminal status.
- Per-row actions: Download, View, Retry, Restore/permanent-delete (trash view).
- Bulk-select action bar: tag assign, set type, trash, **Export (CSV/XLSX)**, **bulk zip download**.
- Trash view: per-row permanent delete + "Empty trash" bulk action; storage meter decrements on permanent delete.

#### `/documents/:id`
- Calls `apiDocument(id)` on mount; polls while non-terminal.
- **Preview pane**: `<img>` for images; `<iframe>` for PDFs — fetches its signed URL via `apiPreviewUrl()` (`GET /documents/{id}/preview`), not `apiDownloadUrl()`, so simply opening a document no longer records a `download` activity event on every page load; the explicit Download button still uses `apiDownloadUrl()` and does log one.
- **Tabs**: Extracted Data (key-value + line items + confidence badge, editable via correction UI — feeds the self-learning loop), Metadata (flat field table, editable title/type/date/correspondent), Custom Fields (typed values per the tenant's field catalog), History (per-document activity feed), Raw JSON.
- "Possible duplicate" badge (links to the other document) when `duplicateOfDocumentId` is set.
- Actions: Download, Retry, Re-run AI extraction, Trash/Restore, **Share** (create/list/revoke time-limited public links).

#### `/search`
- Freetext search only (see §8) — structured filters live on `/documents`, not here, by design.
- Search triggers on Enter/Search click. Result snippets via server-generated `<mark>` tags (`ts_headline`).
- Filter panel: document type pills, date dropdown.

#### `/tags`, `/correspondents`, `/custom-fields`, `/views`
- Standard CRUD pages (list + create/edit modal + delete) matching the same list/modal/form pattern.
- `/tags` additionally has an **"Apply rules to existing documents"** action — retroactively runs the match-rule engine over already-ingested docs (paginated, safe to call repeatedly).
- `/correspondents` form includes an **email** field — auto-populated by `.eml` sender linking, or settable manually to seed the auto-link for future emails.
- `/views` "Open" reconstructs the *complete* filter set on `/documents` — its query-string builder now covers every key the Documents page's filter bar can produce (tag, correspondent, vendor, amount range, custom-field filters), where it previously only carried status/type/date/q/sort/inbox and silently dropped the rest.

#### `/settings`
Fully wired to live data — no mock data anywhere in the app. Tabs: **Organisation** (real profile + live storage stats by mime family), **Users & Access** (real multi-row team list, invite modal, per-row role control, pending-invite badge — admin-gated), **Activity** (org-wide paginated audit feed), **Security** / **API Keys** / **Notifications** (explicit "coming soon" panels — deliberately not faked, since faking security controls in a document-archive product is a trust liability).

#### `/accept-invite`, `/reset-password`, `/shared/[token]` (public, outside the authenticated route group)
- `/accept-invite`: lands from the Supabase invite email, sets a password, then bootstraps and enters the app directly (already tenant-scoped, since `app_metadata` was set before the invite was sent).
- `/reset-password`: lands from the Supabase recovery email, sets a new password, then signs out to `/login` for a fresh sign-in.
- `/shared/[token]`: resolves a share token via the public `GET /api/share/{token}` and offers a download; no login required.

### 10.4 TypeScript Types (`types/index.ts`) — current shape, abbreviated

```typescript
type ProcessingStatus = "queued" | "extracting_text" | "ocr_processing" | "ai_extraction" | "completed" | "needs_review" | "failed"
type DocumentType = "invoice" | "receipt" | "contract" | "report" | "letter" | "form" | "other"
type UserRole = "admin" | "user"

interface Document {
  id: string; tenantId: string; filename: string; originalFilename: string; title: string;
  documentType: DocumentType; mimeType: string; sizeBytes: number;
  status: ProcessingStatus; uploadedBy: string; uploadedAt: string;
  processedAt: string | null; documentDate: string | null; pageCount: number | null; hasTextLayer: boolean;
  ocrConfidence: number | null; confidence: number | null;
  extractedData: Record<string, unknown> | null; extractedText: string | null;
  tags: { id: string; name: string; color: string }[];
  correspondent: { id: string; name: string } | null;
  customFieldValues: FieldValue[];
  storageKey: string; hasThumbnail: boolean; deletedAt: string | null;
  duplicateOfDocumentId: string | null;
}

interface SearchResult {
  document: Document; score: number;
  snippet?: string;        // HTML string with <mark> tags from ts_headline
  matchedFields: string[]; // ["content", "filename"]
}
```

Also exported: `SavedView`, `CustomField`, `FieldValue`, `Tag`, `Correspondent`, `Tenant`, `User`, `SearchListResponse`, and `ActivityEvent` (full `type` union: `upload | processing_complete | processing_failed | search | download | user_added | edit | trash | restore | permanent_delete | duplicate_detected | user_removed | role_changed`).

---

## 11. Configuration Reference

All values read from `backend/.env`. Never commit this file.

| Variable | Type | Default | Purpose |
|---|---|---|---|
| `SUPABASE_URL` | string | required | Supabase project URL |
| `SUPABASE_ANON_KEY` | string | required | Public anon key (frontend uses this too) |
| `SUPABASE_SERVICE_ROLE_KEY` | string | required | Admin key; backend + worker only. Bypasses RLS in storage/auth admin calls |
| `SUPABASE_JWT_SECRET` | string | required | HS256 JWT verification secret (Project Settings → API → JWT Secret) |
| `SUPABASE_STORAGE_BUCKET` | string | `"documents"` | Object storage bucket name |
| `DATABASE_URL` | string | required | psycopg3 URL; transaction pooler port 6543; `+psycopg` driver prefix |
| `ALEMBIC_DATABASE_URL` | string | required | Direct session URL; port 5432; used by `alembic upgrade head` |
| `DB_PREPARE_THRESHOLD` | string | `"none"` | `"none"` disables psycopg3 prepared statements (required for transaction pooler) |
| `REDIS_URL` | string | `"redis://localhost:6379/0"` | Redis connection URL |
| `IDP_QUEUE_NAME` | string | `"idp"` | RQ queue name |
| `VLM_BASE_URL` | string | `""` | OpenAI-compatible vLLM endpoint. Empty = AI extraction skipped |
| `VLM_API_KEY` | string | `"none"` | API key for vLLM server |
| `VLM_MODEL` | string | `"Qwen2.5-VL-7B-Instruct"` | Model name sent in chat completion requests |
| `VLM_MAX_MODEL_LEN` | int | `2048` | Server's `--max-model-len` — total context window |
| `VLM_MAX_OUTPUT_TOKENS` | int | `768` | Tokens reserved for JSON response per call |
| `VLM_RENDER_DPI` | int | `120` | DPI for PDF → PNG rasterization in vision mode |
| `VLM_REQUEST_TIMEOUT` | float | `90.0` | HTTP timeout per VLM call (seconds) |
| `VLM_MAX_CHUNK_CALLS` | int | `6` | Hard cap on total VLM calls per document |
| `VLM_MAX_PAGES` | int | `10` | Page ceiling per document in vision mode |
| `CONFIDENCE_THRESHOLD` | float | `0.7` | Minimum confidence to label a **VLM** extraction accepted (the deterministic gate's own 0.75 threshold is hardcoded in `gate.py`, not a Settings field — changing it needs human sign-off) |
| `PROMOTE_AFTER_N` | int | `3` | Reserved: accepted extractions needed before template promotion |
| `MAX_UPLOAD_MB` | int | `50` | Maximum file size in MB (enforced at upload) |
| `LLM_MONTHLY_TOKEN_CAP_DEFAULT` | int | `2,000,000` | Default per-tenant monthly VLM token cap when `tenants.llm_monthly_token_cap` is unset (LLM budget gate, backed by the `ai_usage` table) |
| `TRASH_RETENTION_DAYS_DEFAULT` | int | `30` | Default trash auto-purge window (days) when `tenants.trash_retention_days` is unset |
| `CORS_ALLOW_ORIGINS` | string | `"http://localhost:3000,http://127.0.0.1:3000,http://[::1]:3000"` | Comma-separated list of allowed CORS origins |
| `SENTRY_DSN` | string | `""` | Sentry DSN — **now actually wired** in both `main.py` and `worker.py`, no-op until set |
| `ENV` | string | `"development"` | Environment label; returned in `/api/health` |

**Not a Settings/env field, but worth knowing about:** rate limiting (`slowapi`, `app/core/rate_limit.py`) is configured directly in code per-route (10/hour signup, 300/minute upload, 30/minute public share-resolve) — there's no env var to tune it. Storage quota (`storage_used_bytes`/`storage_limit_bytes`) lives on the `Tenant` model, not in `Settings` either.

**Frontend env vars** (`frontend/.env.local`):
| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key |
| `NEXT_PUBLIC_API_BASE_URL` | Backend API base URL (default: `http://localhost:8000/api` — canonical port **8000**, not 8001) |

---

## 12. Testing

**394 tests, 29 files** (`conftest.py` + 28 test modules), 0 failing as of the last full run.

Run all tests:
```bash
cd backend
./venv/Scripts/python.exe -m pytest app/tests -v
```
**Use the venv's own interpreter** (`backend/venv/Scripts/python.exe`), not a bare `python` on PATH — the system Python is missing `slowapi`/`sentry-sdk`, so anything importing `app.main` fails under it while most individual test files (which don't) silently still pass, giving a misleadingly-clean run.

Unit tests run offline (no DB, no Redis, no VLM). Integration tests require `ALEMBIC_DATABASE_URL` in `.env` and are automatically skipped if it is absent.

| File | What it covers |
|---|---|
| `test_contract_camelcase.py` | camelCase alias contract for `UserOut`/`TenantOut`/`MeOut` |
| `test_idp_pipeline.py` | `run_extraction` dispatch across all mime families (mocked I/O) |
| `test_universal_ingestion.py` | MIME sniffing (all formats incl. XML), office/text/email/XML text extraction, thumbnail dispatch, pipeline dispatch for the full format set |
| `test_deterministic_extraction.py` | `extract_candidate` regex rules + `gate.score_extraction` weighting |
| `test_normalize.py` | `extract_typed_fields` — reads both live extraction schemas (deterministic camelCase, VLM snake_case) |
| `test_ubl_invoice.py` | UBL/MyInvois parser (unit) + a real `process_document` integration test (mocked `tenant_session`/storage) proving the gate-fail-never-calls-VLM guard |
| `test_ai_extraction.py` | VLM text + vision mode, tolerant JSON repair, merge logic, skip path when no endpoint |
| `test_enqueue_on_upload.py` | Enqueue-on-upload, retry validation, upload batch-count cap |
| `test_file_management.py` | Trash/restore/permanent-delete, storage accounting |
| `test_bulk_ops.py` | Bulk trash/tag/set-type |
| `test_export.py` | CSV/XLSX export, zip bulk-download, row/file caps |
| `test_tags.py` | Tag CRUD, match-rule engine (`matches()`), `run_document_matching` incl. email-sender-priority path, retroactive rule backfill |
| `test_correspondents.py` | Correspondent CRUD, `find_or_create_by_sender` (incl. the SAVEPOINT-based race-condition recovery) |
| `test_custom_fields.py` | Custom field catalog + typed value CRUD |
| `test_saved_views.py` | Saved view CRUD |
| `test_shares.py` | Share creation/list/revoke + public token-resolve |
| `test_auth.py` | Invite/list/role-change/remove-user, last-admin guards, starter-tag seeding |
| `test_auto_title_and_duplicates.py` | Auto-title + duplicate-invoice detection |
| `test_settings_and_activity.py` | Activity feed pagination, org rename, storage-by-mime-family, tenant settings incl. trash-retention override |
| `test_document_type_fields.py` | Predefined-field CRUD per document type, upload-time `field_values`/`new_fields`/`attach_fields` |
| `test_custom_field_documents_filter.py` | Integration — custom-field filter/range params on `/documents` + export, type-resolution-server-side guard |
| `test_security_headers.py` | Security headers present on responses; CSP exemption for docs routes; prod-only behaviors |
| `test_trash_retention.py` | Integration — expired vs. recent purge, storage decrement, one summary `ActivityEvent`, rate-limiting, override/default resolution, dedicated cross-tenant isolation proof |
| `test_monitoring.py` | Sentry no-op / init-once |
| `test_search_service.py` | Integration — FTS + trigram ranking, type filter, stored-XSS snippet-neutralization regression |
| `test_search_tenant_isolation.py` | Integration — cross-tenant search isolation |
| `test_tenant_isolation.py` | Integration — cross-tenant RLS isolation across core tables |
| `test_idp_tenant_isolation.py` | Integration + unit — worker-path RLS isolation, `process_document` not-found handling |

**Eval harness** (separate from pytest — `eval/run.py`, `eval/corpus/`): runs the real deterministic pipeline against fixture documents (currently 9: PDFs, scanned images, and one UBL-XML) and reports **deterministic pass rate** (currently 87.5%, target ≥80%) and **LLM share** (currently 11.1%, target 10–20%). Any change to `extract.py`/`gate.py`/parsers must re-run this and report both numbers.

---

## 13. Project File Structure

```
digital_ui/
├── CLAUDE.md                          # AI assistant instructions (this project)
├── read.md                            # This file
├── start-system.ps1                   # Starts backend + worker + frontend (uses backend/venv)
├── log/                               # ~20 dated development logs, one per major work session
│   ├── 2026-06-05-backend-scaffold-progress.md   # ... through Milestones A-E
│   ├── 2026-07-01_phase6_complete_system_startup.md  # Phases 0-6 complete
│   ├── 2026-07-09_production_levelup_l1.md       # Level 1
│   ├── 2026-07-10_level3_data_value.md           # Level 3
│   └── ...
│
├── backend/
│   ├── pyproject.toml                 # Dependencies, ruff/black config, pytest config
│   ├── venv/                          # Project virtualenv — use this python, not the bare system one
│   ├── .env                           # Secrets — never committed
│   ├── eval/
│   │   ├── run.py                     # Eval harness: pass rate + LLM share against eval/corpus
│   │   └── corpus/                    # 9 fixture docs + expected.json pairs
│   ├── app/
│   │   ├── main.py                    # FastAPI app: CORS, rate limiting, security headers, Sentry, 12 router mounts, /health
│   │   ├── worker.py                  # RQ worker entry: SimpleWorker/Worker + queue
│   │   │
│   │   ├── core/
│   │   │   ├── config.py              # Settings (pydantic-settings)
│   │   │   ├── security.py            # verify_token(), TokenData, JWKS client
│   │   │   ├── security_headers.py    # nosniff/CSP/frame-options middleware (added 07-22)
│   │   │   ├── validation.py          # EmailField + length-capping validators (added 07-22)
│   │   │   ├── deps.py                # get_current_user(), get_tenant_db(), require_admin()
│   │   │   ├── db.py                  # SQLAlchemy engine + SessionLocal
│   │   │   ├── tenant_context.py      # set_tenant() GUC, tenant_session() context manager
│   │   │   ├── storage.py             # Supabase Storage adapter (content-addressed keys)
│   │   │   ├── rate_limit.py          # slowapi limiter (per-endpoint limits + global 200/min fallback, fail-open)
│   │   │   ├── monitoring.py          # init_sentry()
│   │   │   ├── ai_budget.py           # llm_allowed(), record_ai_usage() — LLM budget gate
│   │   │   └── camel.py               # CamelModel base class
│   │   │
│   │   ├── models/                    # 18 models — see §4 for full schema
│   │   │
│   │   ├── modules/                    # 12 feature modules; each follows router/service/schemas
│   │   │   ├── auth/                   # bootstrap, invite/roles/remove, tenant profile
│   │   │   ├── files/                  # upload, list, trash, bulk ops, dashboard, activity, retention
│   │   │   │   └── retention.py         # trash auto-purge — opportunistic, rate-limited (see §6 note)
│   │   │   ├── search/                 # freetext search
│   │   │   ├── tags/                   # tag CRUD + assign + match-rule engine + retroactive backfill
│   │   │   ├── correspondents/         # correspondent CRUD + sender-email linking
│   │   │   ├── metadata/               # custom field catalog + typed values + predefined-per-type fields
│   │   │   ├── views/                  # saved views
│   │   │   ├── export/                 # CSV/XLSX export, zip bulk-download
│   │   │   ├── shares/                 # shareable public links (+ the one public router)
│   │   │   ├── templates/, types/      # empty stubs — no HTTP surface (see §6 note)
│   │   │   └── idp/                    # the pipeline — no router; see below
│   │   │       ├── mimetype.py         # content-sniffing (all formats incl. XML)
│   │   │       ├── pipeline.py         # run_extraction() dispatch, run_ai_extraction()
│   │   │       ├── parsing.py          # PDF text-layer + rasterization
│   │   │       ├── ocr.py              # RapidOCR
│   │   │       ├── office_parsing.py   # DOCX/XLSX/PPTX/text/email extraction + sender parsing
│   │   │       ├── ubl_invoice.py      # MyInvois/UBL-XML parser
│   │   │       ├── extract.py          # deterministic regex extraction
│   │   │       ├── gate.py             # quality gate (0.75 threshold)
│   │   │       ├── normalize.py        # extract_typed_fields() — reads both extraction schemas
│   │   │       ├── extraction.py       # VLM two-phase / vision extraction
│   │   │       ├── thumbnails.py       # generate_thumbnail()
│   │   │       ├── jobs.py             # process_document(), ai_extract_document()
│   │   │       └── queue.py            # enqueue_document(), enqueue_ai_extraction()
│   │   │
│   │   ├── migrations/versions/       # 0001-0016 — see §4.3 for the full list
│   │   │
│   │   └── tests/                     # 29 files, 394 tests — see §12
│   │
└── frontend/
    ├── package.json / tsconfig.json / tailwind.config.ts
    └── app/, components/, lib/, types/, public/       # see §10.1 for the full current tree
```

---

# Part 2 — Plain-English Guide

---

## 14. What is DataWiz?

DataWiz is a **cloud document archive for businesses**. Think of it like a smart filing cabinet that lives on the internet.

You upload **anything** — invoices, receipts, contracts, reports, scanned paperwork, spreadsheets, emails, even e-invoices — and the system:
- **Stores it securely** in the cloud
- **Reads it automatically** — text, a thumbnail, and useful metadata for every single file, no matter the type
- **Pulls out structured data** where it makes sense (who sent an invoice, how much it's for, what items were purchased) — a cost-saving bonus layered on top, not a gate that blocks anything from being archived
- **Makes everything searchable** — by a word inside the document, the filename (even misspelled), or structured filters like amount range and sender
- **Organises it for you** — tags, senders/correspondents, custom fields, saved filter presets

It's built for **small businesses in Malaysia** (PDPA-aware) that deal with a lot of paperwork and want it organised and easy to find. **Retrieval is the headline feature** — if you can't find a file in seconds, nothing else matters.

**The biggest design goal: keep costs low.** The system does as much work as possible using free or cheap methods, and only calls the expensive AI as a last resort, on the hard 10–20% of documents. Most documents are processed at near-zero cost.

---

## 15. How It Works — Step by Step

### Step 1: You log in

You visit the website and sign in with your email and password.

The system:
- Verifies your identity using Supabase Auth (an industry-standard authentication service)
- Creates your private workspace if it's your first time — called a **tenant**
- Every piece of data you upload belongs to your tenant and is invisible to other companies

### Step 2: You upload a document

You drag a PDF or image into the upload page and click Upload.

The system:
- Saves the file to secure cloud storage (Supabase Storage, similar to Google Cloud Storage)
- Creates a database record with the file's details (name, size, type, who uploaded it)
- Immediately puts a "process this document" job into a queue
- The upload page returns instantly — you don't wait for processing to finish

### Step 3: The system reads the document (in the background)

A background worker picks up the job and runs it through a cost cascade — each step only happens if the cheaper one before it couldn't finish the job:

**Parse (free)** — every file type has its own free, instant parser: digital PDFs read their text layer directly, Word/Excel/PowerPoint files are read natively, plain text/CSV/Markdown decode directly, emails split into headers + body, and e-invoice XML (Malaysia's MyInvois format) is read as the structured data it already is.

**OCR (cheap, if needed)** — only for scanned PDFs and photos, where the text is baked into the image. Runs on the server's CPU (RapidOCR, open-source, free) — no GPU needed.

**Deterministic field extraction + quality check** — for anything that looks like an invoice or receipt, the system tries to pull out the vendor, invoice number, dates, and total amount using plain rules (pattern matching, not AI), then scores how confident it is in its own answer. If the score clears the bar (75%), it's done — free, instant, no AI involved. This is how the large majority of invoices get processed.

**AI, only as a last resort** — if the free method's confidence score doesn't clear the bar (about 1 in 5-10 documents), the system sends it to an AI model (a Visual Language Model on a GPU server) as an exception handler. If even that can't produce a confident answer, the document is flagged for a quick human look rather than guessed at — it's still fully archived and searchable either way.

**Make it useful** — a thumbnail is generated, the text is indexed for search, tags and the sender/correspondent are auto-matched, and if a vendor + invoice number were found, the document is auto-titled and checked against everything else you've archived for a possible duplicate.

Every file — even ones with no invoice data to extract, like a contract or a photo — still gets stored, given a thumbnail, and made fully searchable. Structured extraction is a bonus for invoice-shaped documents, never a requirement for archiving.

### Step 4: You view, organise, and search your documents

- The Documents page lists everything with filters (status, type, tag, sender, date, amount range), grid or table view, and bulk actions (tag, trash, export, download as zip)
- The Document Viewer shows the original file alongside extracted data, editable metadata, custom fields, and a full history of what happened to it
- The Search page finds documents by content, filename, or a slightly misspelled filename
- Tags, correspondents, and custom fields let you organise the archive your way; saved views remember a filter setup for one-click reuse
- Share a document with someone outside your team via a time-limited link — no account needed on their end

### What "tenant isolation" means (simply)

DataWiz is a **multi-tenant** system — many companies use the same software, but each company's data is completely separate. It's like a building with many apartments: you have your own apartment (tenant), and no one else can walk into it. The locks are enforced at the database level, not just the app level — even if there were a bug in the app code, the database would still refuse to show you someone else's data.

---

## 16. What's Already Built

### Authentication & Team Accounts ✅
- Sign in with email and password; forgot-password flow
- Automatic first-login setup — no manual admin configuration needed, and a new workspace starts pre-seeded with a few starter tags and a first-run checklist
- **Invite teammates by email**, admin/member roles, a real team-management page — no longer one-admin-per-workspace
- Secure JWT token verification (HS256 and JWKS-based algorithms both supported)

### Universal Document Ingestion ✅
- Upload **any file type**: PDF, scanned PDF, JPEG/PNG/WebP/TIFF, Word/Excel/PowerPoint, text/CSV/Markdown, email (`.eml`), and e-invoice XML (Malaysia's MyInvois/UBL format)
- Take a photo directly from a phone (installable as an app on a home screen)
- Every file gets text, a thumbnail, and metadata — regardless of type
- Duplicate files (identical content) are detected and not re-stored
- File size and per-upload batch limits enforced; upload/signup rate-limited against abuse

### Deterministic-First Extraction ✅
- Plain-rule extraction (no AI) handles the large majority of invoices/receipts at zero cost, checked by an automatic confidence score
- AI (a Visual Language Model) only runs as a fallback on the documents the free method couldn't confidently handle — kept to roughly 1 in 5-10 documents by design, with a monthly budget cap per workspace
- Malaysia e-invoices (MyInvois/UBL-XML) skip extraction entirely — the data's already structured, so it's read directly with no OCR or AI involved
- Every extraction attempt is logged for audit; nothing is ever silently dropped

### Organisation & Data Value ✅
- Tags (with auto-match rules), senders/correspondents (auto-linked from email senders or match rules), custom fields, saved filter presets
- **Custom fields can be predefined per document type** (e.g. Invoices always ask for PO Number, Contracts always ask for Contract End Date) — the upload screen prompts for exactly the right fields instead of showing one giant undifferentiated list, and those fields are filterable/searchable on the Documents page once a type is picked
- Filter by amount range and vendor, not just status and type
- Export filtered results to CSV/Excel, or download a batch as a zip
- Retroactively apply your tagging rules to documents you uploaded before you set the rules up
- Auto-title from vendor + invoice number, and a heads-up when a document looks like a duplicate invoice
- Time-limited shareable links for sending a document to someone outside the workspace

### Document Library, Viewer & Trash ✅
- Filterable, sortable document list with grid/table toggle and bulk actions
- Inline preview, editable metadata, custom field values, and a per-document activity history
- Soft-delete (trash) with restore and permanent-delete, and a storage meter that actually reflects what's been freed
- **Trash auto-retention**: trashed documents are automatically purged for good after a set number of days (30 by default, adjustable per workspace in Settings), so abandoned trash doesn't quietly accumulate storage cost forever — the Trash view shows a "purges in N days" countdown on every row so nothing disappears as a surprise

### Search ✅
- Full-text search by word or phrase, partial-word ("inv" finds "invoice"), and typo-tolerant filename matching
- Structured filters (status, type, tag, sender, date, amount) live on the Documents page as a separate, more powerful surface from the freetext Search page
- Highlighted excerpts show exactly where your search term matched

### Dashboard, Trust & Security ✅
- Real organisation profile and live storage usage (no placeholder data anywhere in Settings)
- Org-wide and per-document audit trail (every upload, edit, tag, trash, invite, role change)
- Error monitoring (Sentry) wired in, configured to never capture document text or personal data
- Every company's data is isolated at the database level (Row-Level Security), enforced by a database role that cannot bypass it — not just an app-level convenience check
- Security headers on every response, production error pages that never leak stack traces, a global request-rate ceiling that still works even if Redis goes down, and tightened input validation on every free-text field
- A found-and-fixed stored-XSS bug in search result highlighting (a malicious document could otherwise have run script in another user's browser) — now covered by a permanent regression test
- 394 automated tests, including dedicated tenant-isolation coverage for both the API and the background worker

---

### In progress: 2026-07-27 full feature QA + bugfix pass

Every user-facing feature except the IDP pipeline's extraction internals is being manually
re-tested end-to-end (real browser, fresh throwaway tenant) and fixed as issues surface. **Fixes
so far are made in the working tree but not yet committed or covered by new tests** — treat the
descriptions above as the current, not-yet-shipped truth:
- Viewing a document's inline preview was recording it as a "download" in the audit trail on
  every page load; it now uses a dedicated preview endpoint that doesn't log an activity event.
- The Documents page had no vendor/amount-range filter inputs even though the API has supported
  them since Level 3 — added to the filter bar.
- Filters encoded in a URL (the sidebar's Inbox link, a saved view's "open" link) weren't applied
  by the Documents page — it only read its filter state from local component state, never the URL.
- Saved views silently dropped tag/correspondent/vendor/amount/custom-field filters when
  reconstructing a view's URL, keeping only status/type/date/q/sort/inbox.
- New tenants (post-migration-0015 signups) got an empty Custom Fields catalog; bootstrap now
  seeds the same starter predefined fields the migration backfilled for existing tenants.
- Upload page's file picker didn't accept XML (`.xml` / UBL/MyInvois e-invoices) even though the
  backend has parsed it since Level 5; a stale "OCR via LiteParse" string was also corrected to
  RapidOCR (LiteParse was dropped for stability reasons before this ever shipped).

Once the pass completes, a dedicated log (`log/2026-07-27_full_feature_qa_pass.md`) will record
every area tested with pass/fail verdicts, and these fixes will be committed with `pytest`/`tsc`
verified green.

---

## 17. What's Coming Next

### Blocked on external setup

| Item | What it needs |
|---|---|
| **Upgraded extraction engine** (better table/layout handling on hard scans) | A GPU endpoint the team needs to deploy and hand over the URL/key for; also needs a quick license check before it ships |

### Planned, not yet started

| Feature | Description |
|---|---|
| **Forward emails straight into the archive** | A dedicated inbox address per workspace — no manual upload step at all. Needs a mail-routing domain set up first |
| **Better Malay-language search** | Search currently favours English word stemming; a small config change improves recall for Malay documents |

### Deliberately out of scope (do not build without explicit approval)

- Microservices or separate containers per feature
- Elasticsearch or external search cluster
- Cross-encoder reranking for search
- Schema-per-tenant database isolation (current RLS approach is sufficient and free)
- Native mobile app (the installable web app + camera capture covers the core mobile need)
- Multi-region deployment
- SSO / SAML enterprise login
- Batch LLM API calls
- Analytics/BI dashboards (export covers the real need without adding a whole new surface)

---

*Last updated: 2026-07-27*
*Complete: Milestones A-E, Phases 0-6 (production hardening → universal ingestion → deterministic extraction → file management → organization → metadata → retrieval/UX), and Production Level-Up Levels 1, 3, 4, and 5 (5 of 7 items — trash auto-retention shipped 2026-07-23; email-in ingestion and Malay FTS config dropped by user request 2026-07-27). Level 2 (IDP pipeline upgrade) is blocked on external GPU setup. A dedicated security-hardening pass (headers, prod error hygiene, global rate-limit fallback, input validation, a stored-XSS fix in search) shipped 2026-07-22, plus predefined-per-document-type custom fields shipped 2026-07-16. **Underway now: a full feature QA + bugfix pass (see "In progress" above §17) with several fixes already made but not yet committed.** See `CLAUDE.md` for the live status table.*
