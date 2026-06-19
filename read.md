# DataWiz Digital Archive — Complete Project Reference

> Full technical and plain-English documentation of everything built and everything planned.

---

## Table of Contents

**Part 1 — Technical Reference**
1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Database Schema](#4-database-schema)
5. [Security & Multi-Tenancy](#5-security--multi-tenancy)
6. [Backend API — All Endpoints](#6-backend-api--all-endpoints)
7. [IDP Pipeline — Stage by Stage](#7-idp-pipeline--stage-by-stage)
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

# Part 1 — Technical Reference

---

## 1. Project Overview

**DataWiz Digital Archive** is a multi-tenant SaaS document archive system with an Intelligent Document Processing (IDP) pipeline. Users upload PDFs, scanned documents, and images; the system stores them securely, extracts text and structured data automatically, and makes everything fast and searchable.

**Design principle — the 10–15% AI rule:**
Deterministic code (text extraction, OCR, full-text search) handles ~85–90% of the work. The AI/VLM layer is the exception handler — only invoked after all cheaper options are exhausted. This keeps infrastructure cost near zero.

**Cost cascade (cheapest first):**
1. Digital PDF with a text layer → read text directly via PyMuPDF — **free, instant**
2. Scanned PDF or image → CPU OCR via RapidOCR — **cheap, no GPU**
3. Structured data extraction → VLM (GPU) call — **only when the above paths complete**
4. Search → Postgres FTS + trigram — **no external search cluster**

**Target infrastructure cost:** ~$0/month (Supabase free tier + Lightning AI Studio GPU only when processing documents).

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
│  Login → Supabase Auth SDK → JWT stored in localStorage         │
│  Every API call: Authorization: Bearer <JWT>                     │
└─────────────────────┬───────────────────────────────────────────┘
                      │ HTTPS / JWT
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                 FastAPI Backend (:8001)                          │
│  CORS Middleware (whitelist from CORS_ALLOW_ORIGINS)            │
│  ├── GET  /api/health                                           │
│  ├── POST /api/auth/bootstrap  ──► Supabase Auth Admin API      │
│  ├── GET  /api/auth/me                                          │
│  ├── POST /api/documents       ──► Supabase Storage (upload)    │
│  ├── GET  /api/documents                                        │
│  ├── GET  /api/documents/{id}                                   │
│  ├── GET  /api/documents/{id}/download ──► Signed URL (5 min)  │
│  ├── POST /api/documents/{id}/retry                             │
│  ├── POST /api/documents/{id}/extract                           │
│  ├── POST /api/documents/extract-missing                        │
│  ├── GET  /api/dashboard                                        │
│  └── GET  /api/search                                           │
│                                                                 │
│  Every authenticated route:                                     │
│   1. verify_token(Bearer JWT) → TokenData                       │
│   2. db.begin() → SET LOCAL app.current_tenant = :tenant_id    │
│   3. RLS enforces tenant boundary on every SQL query            │
└──────────────┬──────────────────────────────┬───────────────────┘
               │ SQLAlchemy + psycopg3         │ enqueue (Redis)
               ▼                              ▼
┌──────────────────────────┐   ┌─────────────────────────────────┐
│  PostgreSQL (Supabase)   │   │      Redis Queue  (idp)         │
│                          │   └──────────────┬──────────────────┘
│  Tables (RLS on all):    │                  │ RQ job
│  ├── tenants             │                  ▼
│  ├── users               │   ┌─────────────────────────────────┐
│  ├── documents           │   │   Worker (python -m app.worker) │
│  ├── document_types      │◄──│                                 │
│  ├── document_templates  │   │  Stage 1: PyMuPDF text extract  │
│  ├── extractions         │   │  Stage 2: RapidOCR (if needed)  │
│  ├── processing_jobs     │   │  Stage 3: VLM extraction        │
│  ├── activity_events     │   │     Phase 1: header (1 call)    │
│  └── api_keys            │   │     Phase 2: line items (N call)│
│                          │   │  Stage 4: populate search_tsv   │
│  Indexes:                │◄──│  → doc.status = 'completed'     │
│  ├── GIN(search_tsv)     │   └─────────────┬───────────────────┘
│  ├── GIN(filename trgm)  │                 │ download_file / upload_file
│  └── GIN(extracted_data) │                 ▼
└──────────────────────────┘   ┌─────────────────────────────────┐
                               │   Supabase Storage (S3)         │
                               │   tenants/{tid}/docs/{id}.ext   │
                               └─────────────────────────────────┘
                                             │ OpenAI API call
                                             ▼
                               ┌─────────────────────────────────┐
                               │  Lightning AI Studio (vLLM)     │
                               │  Qwen3-VL-4B-Instruct           │
                               │  max_model_len: 2048 tokens     │
                               │  OpenAI-compatible endpoint     │
                               └─────────────────────────────────┘
```

**Request lifecycle (upload example):**
1. Browser POSTs multipart form to `POST /api/documents`
2. FastAPI verifies JWT, opens DB session, sets GUC tenant
3. File bytes uploaded to Supabase Storage; `Document` + `ProcessingJob` rows inserted; `ActivityEvent(upload)` logged
4. After commit, `enqueue_document(doc_id, tenant_id)` pushes an RQ job to Redis
5. Worker picks up the job: downloads file bytes from storage, runs extraction pipeline, populates `extracted_text`, `extracted_data`, `search_tsv`, sets `status = completed`
6. Frontend polls `GET /api/documents/{id}` every 3 seconds; once status is `completed`, stops polling and renders the Extracted Data tab

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

### Worker extras (installed in worker image only)

| Package | Version | Purpose |
|---|---|---|
| PyMuPDF | ≥1.24 | PDF text-layer extraction + page rasterization (`import fitz`) |
| rapidocr-onnxruntime | ≥1.2.3 | CPU OCR — no system deps, Windows-compatible, pip-only |
| Pillow | ≥10.3 | Image conversion (RGB) + resize for VLM vision mode |
| openai | ≥1.40 | OpenAI-compatible client for vLLM endpoint |
| jsonschema | ≥4.22 | Reserved for future schema-guided extraction validation |

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

All tenant-owned tables have a non-nullable `tenant_id UUID` column and an RLS policy that enforces `tenant_id = current_setting('app.current_tenant', true)::uuid`. The `tenants` table is special — its RLS policy uses `id = ...` instead.

### `tenants`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Python-side `uuid4()` default |
| `name` | VARCHAR NOT NULL | Derived from email domain at first login |
| `plan` | VARCHAR NOT NULL | `"starter"` default; future: `professional / enterprise` |
| `storage_used_bytes` | BIGINT NOT NULL | Incremented on upload; default 0 |
| `storage_limit_bytes` | BIGINT NOT NULL | Default 10 GB (`10 * 1024³`) |
| `created_at` | TIMESTAMPTZ | `server_default=now()` |

### `users`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Equal to Supabase auth `sub` (UUID) |
| `tenant_id` | UUID FK→tenants CASCADE | Indexed |
| `email` | VARCHAR NOT NULL UNIQUE | |
| `name` | VARCHAR NOT NULL | Derived from email username |
| `role` | VARCHAR NOT NULL | `"admin"` or `"user"`; default `"user"` |
| `avatar_initials` | VARCHAR NOT NULL | 1–2 uppercase letters; default `""` |
| `created_at` | TIMESTAMPTZ | |
| `last_login_at` | TIMESTAMPTZ nullable | Updated on every bootstrap call |

### `documents`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants CASCADE | Indexed |
| `filename` | VARCHAR NOT NULL | Safe display name |
| `original_filename` | VARCHAR NOT NULL | As uploaded by the user |
| `mime_type` | VARCHAR NOT NULL | Validated against allow-list at upload |
| `size_bytes` | BIGINT NOT NULL | |
| `storage_key` | VARCHAR NOT NULL | `"{tenant_id}/docs/{doc_id}.{ext}"` |
| `status` | VARCHAR NOT NULL | State machine (see below); default `"queued"` |
| `error_message` | TEXT nullable | Set on `failed`; capped at 2000 chars |
| `document_type` | VARCHAR NOT NULL | Denormalized enum; default `"other"` |
| `document_type_id` | UUID FK→document_types SET NULL | nullable |
| `template_id` | UUID FK→document_templates SET NULL | nullable |
| `layout_fingerprint` | VARCHAR nullable | Reserved for template matching |
| `page_count` | INTEGER nullable | Set after pipeline |
| `has_text_layer` | BOOLEAN NOT NULL | Default `false` |
| `ocr_used` | BOOLEAN NOT NULL | Default `false` |
| `ocr_confidence` | REAL nullable | Mean per-line OCR score 0.0–1.0 |
| `extracted_data` | JSONB nullable | Structured fields from VLM |
| `extracted_text` | TEXT nullable | Raw text from extraction |
| `confidence` | REAL nullable | VLM confidence score 0.0–1.0 |
| `tags` | VARCHAR[] NOT NULL | Default `{}` |
| `search_tsv` | TSVECTOR nullable | FTS index column; updated by worker |
| `uploaded_by` | UUID FK→users RESTRICT | |
| `uploaded_at` | TIMESTAMPTZ | `server_default=now()` |
| `processed_at` | TIMESTAMPTZ nullable | Set when `status=completed` |

**Document status machine:**
```
queued → extracting_text → [ocr_processing] → ai_extraction → completed
                                                             → failed
```
Any stage can transition to `failed`. The worker re-raises exceptions so RQ records the failure and schedules a retry (max 3 attempts).

### `document_types`
Stores document type definitions. `tenant_id = NULL` means system/global type (seeded in migration 0003).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants nullable | NULL = system type |
| `name` | VARCHAR NOT NULL | e.g. `"invoice"`, `"receipt"` |
| `description` | TEXT nullable | |
| `json_schema` | JSONB nullable | Soft schema for future confidence scoring |
| `is_system` | BOOLEAN NOT NULL | Default `false` |
| `created_at` | TIMESTAMPTZ | |

**Seeded system types (migration 0003):** `invoice`, `receipt`, `contract`, `report`, `letter`, `form`, `other`.

### `document_templates`
Captures learned document layouts for future deterministic extraction (post-MVP).

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
Audit trail for every VLM attempt. One row per extraction run (including failures).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants CASCADE | Indexed |
| `document_id` | UUID FK→documents CASCADE | Indexed |
| `template_id` | UUID FK→document_templates SET NULL nullable | |
| `method` | VARCHAR NOT NULL | `"vlm"` / `"deterministic"` / `"manual"` |
| `model_name` | VARCHAR nullable | e.g. `"Qwen/Qwen3-VL-4B-Instruct"` |
| `output` | JSONB nullable | Extracted fields, or `{"_error": ..., "_mode": ...}` on failure |
| `confidence` | REAL nullable | |
| `status` | VARCHAR NOT NULL | `"accepted"` / `"low_confidence"` / `"corrected"` |
| `created_at` | TIMESTAMPTZ | |

### `processing_jobs`
One row per document; tracks pipeline execution state.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants CASCADE | Indexed |
| `document_id` | UUID FK→documents CASCADE | Indexed |
| `status` | VARCHAR NOT NULL | `"queued"` / `"running"` / `"completed"` / `"failed"` |
| `stage` | VARCHAR nullable | Current stage: `"text_extraction"` / `"ocr_processing"` / `"ai_extraction"` |
| `attempts` | INTEGER NOT NULL | Incremented on each RQ execution; default 0 |
| `error` | TEXT nullable | Error message on failure |
| `enqueued_at` | TIMESTAMPTZ | `server_default=now()` |
| `started_at` | TIMESTAMPTZ nullable | |
| `finished_at` | TIMESTAMPTZ nullable | |
| `duration_ms` | INTEGER nullable | Wall-clock processing time |

### `activity_events`
Append-only event log for the dashboard activity feed.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants CASCADE | Indexed |
| `type` | VARCHAR NOT NULL | `"upload"` / `"processing_complete"` / `"processing_failed"` / `"search"` / `"download"` / `"user_added"` |
| `document_id` | UUID FK→documents SET NULL nullable | |
| `document_name` | VARCHAR nullable | Denormalized at event time |
| `user_id` | UUID FK→users SET NULL nullable | |
| `user_name` | VARCHAR NOT NULL | Denormalized at event time |
| `timestamp` | TIMESTAMPTZ | `server_default=now()` |
| `meta` | TEXT nullable | Error excerpt on `processing_failed` events |

### `api_keys`
Stored for future API key authentication (not yet wired to routes).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants CASCADE | Indexed |
| `name` | VARCHAR NOT NULL | Display name |
| `prefix` | VARCHAR NOT NULL | Shown in UI (e.g. `"dw_abc123"`) |
| `hashed_key` | VARCHAR NOT NULL | Never stores raw key |
| `created_at` | TIMESTAMPTZ | |
| `last_used_at` | TIMESTAMPTZ nullable | |

### 4.2 Indexes

| Index | Table | Type | Used for |
|---|---|---|---|
| `ix_documents_search_tsv` | documents | GIN | FTS `@@` operator on `search_tsv` |
| `ix_documents_filename_trgm` | documents | GIN `gin_trgm_ops` | `word_similarity()` fuzzy filename |
| `ix_documents_extracted_gin` | documents | GIN `jsonb_path_ops` | `@>` queries on `extracted_data` |
| `ix_documents_tags` | documents | GIN | Array `@>` on `tags` |
| `ix_documents_tenant_id` | documents | B-tree | Tenant-scoped list queries |
| `ix_documents_uploaded_by` | documents | B-tree | FK join to users |
| `ix_users_tenant_id` | users | B-tree | |
| `ix_extractions_tenant_id` | extractions | B-tree | |
| `ix_extractions_document_id` | extractions | B-tree | Per-doc audit queries |
| `ix_processing_jobs_tenant_id` | processing_jobs | B-tree | |
| `ix_processing_jobs_document_id` | processing_jobs | B-tree | Job lookup by doc |
| `ix_activity_events_tenant_id` | activity_events | B-tree | Dashboard feed |

### 4.3 Migrations

| Revision | File | What it does |
|---|---|---|
| `0001` | `0001_initial_tables.py` | Creates all 9 tables. Enables `pgcrypto` and `pg_trgm` extensions. Creates all 16 indexes listed above. |
| `0002` | `0002_rls_policies.py` | Enables `ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` on all 9 tables. Creates one `USING` + `WITH CHECK` policy per table using `current_setting('app.current_tenant', true)::uuid`. |
| `0003` | `0003_seed_system_document_types.py` | Bulk-inserts 7 system document types (`tenant_id=NULL`, `is_system=true`): invoice, receipt, contract, report, letter, form, other. |
| `0004` | `0004_grant_app_roles.py` | `GRANT USAGE ON SCHEMA public TO authenticated`. `GRANT SELECT/INSERT/UPDATE/DELETE` on all 9 tables to the `authenticated` role so tests can switch roles to enforce RLS. |
| `0005` | `0005_fix_rls_nullif.py` | Drops and recreates all RLS policies with `NULLIF(current_setting('app.current_tenant', true), '')::uuid`. Fixes Supabase PostgreSQL returning `""` (empty string) instead of `NULL` when the GUC is unset — ensures fail-closed: no GUC = 0 rows. |

**How to run migrations:**
```bash
cd backend
alembic upgrade head
```
Uses `ALEMBIC_DATABASE_URL` (direct session connection, port 5432) — not the transaction pooler.

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
2. Calls `supabase_admin().auth.admin.update_user_by_id(user_id, {"app_metadata": {"tenant_id": "...", "role": "admin"}})` → patches the Supabase user record so all future JWTs carry the tenant.
3. Creates a `User` row with `role="admin"`.
4. Subsequent logins hit the idempotent path: upserts user, updates `last_login_at`, syncs role.

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

- Files are stored at `tenants/{tenant_id}/docs/{doc_id}.{ext}` in Supabase Storage.
- The API **never streams file bytes** in HTTP responses. It issues signed URLs via `storage.create_signed_url(key, expires_in=300)` (5-minute TTL).
- Download route: verifies the document belongs to the tenant (RLS-checked `db.get`), then calls the storage adapter for a signed URL.
- Worker downloads files using the service role key — only the worker runs with elevated privileges, never the public API.

### 5.5 Input Validation

- **File MIME type**: checked against an explicit allow-list (`application/pdf`, `image/jpeg`, `image/png`, `image/webp`, `image/tiff`). Unknown types → HTTP 415.
- **File size**: checked against `settings.max_upload_mb` → HTTP 413.
- **CORS**: origins validated against `settings.cors_origins_list` (comma-separated from `CORS_ALLOW_ORIGINS`).
- **All SQL**: parameterized via SQLAlchemy `func.*` or `text(..., {"param": value})` — no raw string interpolation.

---

## 6. Backend API — All Endpoints

Base URL: `http://localhost:8001/api` (dev). All authenticated routes require `Authorization: Bearer <JWT>`.

All response bodies use **camelCase** field names (via `CamelModel` alias generator). All `id` fields are UUID strings.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/health` | None | Liveness check. Returns `{"status":"ok","env":"development"}` |
| `POST` | `/auth/bootstrap` | JWT (no tenant) | Create/upsert tenant + user. Returns `MeOut` |
| `GET` | `/auth/me` | JWT (no tenant) | Same as bootstrap (idempotent upsert). Returns `MeOut` |
| `POST` | `/documents` | JWT + tenant | Upload files (multipart). Returns `DocumentListOut` |
| `GET` | `/documents` | JWT + tenant | List documents. Query: `status`, `type`, `q`, `sort`, `page` |
| `GET` | `/documents/{id}` | JWT + tenant | Fetch single document |
| `GET` | `/documents/{id}/download` | JWT + tenant | Returns `{"url":"<signed-url>"}` (5-min TTL) |
| `POST` | `/documents/{id}/retry` | JWT + tenant | Re-enqueue a `failed` document. Returns updated doc |
| `POST` | `/documents/{id}/extract` | JWT + tenant | Re-run VLM extraction only (doc stays completed). Returns doc |
| `POST` | `/documents/extract-missing` | JWT + tenant | Enqueue VLM extraction for all completed docs with no `extracted_data`. Returns `{"enqueued":N}` |
| `GET` | `/dashboard` | JWT + tenant | Returns stats + recent docs + activity feed |
| `GET` | `/search` | JWT + tenant | Full-text + fuzzy search. Query: `q`, `type`, `date`, `status`, `page` |

### Upload — `POST /api/documents`

**Request:** `multipart/form-data`
- `files`: one or more files (`UploadFile[]`)
- `document_type`: optional repeated string field; index-matched to files; defaults to `"other"`

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

## 7. IDP Pipeline — Stage by Stage

The pipeline runs in the RQ worker process (`python -m app.worker`). Entrypoint: `app/modules/idp/jobs.py :: process_document(doc_id, tenant_id)`.

### Stage 1 — Text Extraction (`app/modules/idp/parsing.py` + `pipeline.py`)

```
file_bytes + mime_type
     │
     ├── image/* → _extract_image() → ocr_image() → ExtractionResult
     │
     └── application/pdf → _extract_pdf()
           │
           ├── fitz.open(stream=bytes) → doc
           ├── extract_text_layer(doc) → raw_text = join(page.get_text("text"))
           │
           ├── has_usable_text_layer(text, page_count)?
           │     threshold: non-whitespace chars ≥ max(16, 8 × page_count)
           │
           ├── YES → ExtractionResult(has_text_layer=True, ocr_used=False)  [FREE PATH]
           │
           └── NO → rasterize_page(page, dpi=200) per page
                     → ocr_image(png_bytes) per page
                     → concatenate with "\n\n"
                     → mean confidence
                     → ExtractionResult(has_text_layer=False, ocr_used=True)
```

**`parsing.py` functions:**
- `open_pdf(data)` → `fitz.open(stream=data, filetype="pdf")`
- `extract_text_layer(doc)` → joins `page.get_text("text")` for all pages
- `has_usable_text_layer(text, page_count)` → `len(text.replace(" ","").replace("\n","")) >= max(16, 8 * page_count)`
- `rasterize_page(page, dpi=200)` → `fitz.Matrix(zoom, zoom)` where `zoom = dpi / 72.0`; returns PNG bytes

### Stage 2 — OCR (`app/modules/idp/ocr.py`)

Used when no usable text layer, or for image files.

```
png_bytes
  → PIL.Image.open() → convert("RGB")
  → numpy.array(image)
  → RapidOCR()(array) → list of [box, text, score]
  → join lines with "\n"
  → mean score across lines
  → return (text: str, confidence: float)
```

`RapidOCR` engine is a **process-level singleton** (`_engine = None`, initialized on first call). Loading the ONNX model takes ~1–2 seconds; subsequent calls are fast.

### Stage 3 — VLM Structured Extraction (`app/modules/idp/extraction.py`)

#### Token Budget Math (config-driven)
```
vlm_max_model_len    = 2048   (total context window: input + output)
vlm_max_output_tokens = 256   (tokens reserved for model's JSON response)
prompt_overhead       = 200   (system prompt + user message wrapper)
safety_margin         = 50

input_budget = max(256, 2048 − 256 − 200 − 50) = 1542 tokens
text_chunk_chars = 1542 × 1.35 ≈ 2081 chars per chunk
images_per_call  = max(1, min(2, 1542 // 340)) = 2 images per call (at 512px)
```

All these values adjust automatically when you change `.env` settings.

#### Text Mode (digital PDF — has_text_layer = True)

Called when `has_text_layer=True` and `len(extracted_text) >= 8`. Runs `_extract_two_phase(text, client)`.

**Phase 1 — Header extraction** (1 VLM call):
- Takes the first text chunk only.
- Uses `_HEADER_PROMPT`: instructs the model to extract header fields only and explicitly prohibit `line_items`.
- Fields extracted: `vendor`, `invoice_number`, `invoice_date`, `total_amount`, `currency`, `buyer`, `buyer_address`, `vendor_address`, `gst`, `grand_total`, `terms_conditions`.
- The `line_items` key is stripped from the result even if the model includes it.

**Phase 2 — Line items extraction** (up to `vlm_max_chunk_calls − 1` calls):
- One call per text chunk (all chunks including the first, for line item content).
- Uses `_LINE_ITEMS_PROMPT`: instructs the model to extract every product/service row exhaustively.
- Each item: `{"code": "...", "description": "...", "qty": N, "unit_price": N, "amount": N}`.
- Up to 9 calls (with `VLM_MAX_CHUNK_CALLS=10`).

**Why two phases?**
With a 256-token output budget, a single call must choose between header fields and line items. Splitting the calls gives each concern the full budget: ~12 compact line items fit in 256 tokens.

#### Vision Mode (scanned / image — has_text_layer = False)

```
file_bytes + mime_type
  → render_page_images(file_bytes, mime, max_pages=10, dpi=120)
       image/* → [_resize_for_vlm(bytes, max_side=512)]
       PDF    → rasterize_page(page, dpi=120) per page → _resize_for_vlm each
  → _batch_images(images, images_per_call=2)
  → per batch: build content=[{type:"image_url", image_url:{url:"data:image/png;base64,..."}}]
  → _call_vlm(client, content, _SYSTEM_PROMPT)
  → _tolerant_parse each response
  → _merge_extractions(parts)
```

#### Output Repair — `_tolerant_parse(text)`

The 256-token limit often truncates the model's JSON mid-value or mid-key. The tolerant parser has 4 fallback layers:

1. Strip ` ```json ... ``` ` code fences.
2. `json.loads(text)` — if the output is well-formed.
3. Find the outermost `{...}` span and try again (handles trailing prose).
4. `_repair_truncated_json(s)` — stack-based bracket tracker:
   - Scans character by character; tracks open `{` / `[` on a stack; tracks whether inside a string.
   - On exhaustion: closes any open string with `"`, strips trailing commas, removes dangling key strings (e.g. `,"descriptio"` — a key that was truncated before its colon+value), closes remaining open brackets in reverse stack order.
   - Example: `{"items":[{"x":1},{"desc` → `{"items":[{"x":1},{"desc"}]}` — partially salvaged.

#### Merge — `_merge_extractions(parts)`

When multiple VLM calls return partial results, they are merged into one `VlmExtraction`:

| Field type | Merge strategy |
|---|---|
| `documentType` | Majority vote among non-`"other"` values; falls back to `"other"` |
| `confidence` | Arithmetic mean across all parts |
| List fields (e.g. `line_items`) | Concatenated in call order |
| Scalar fields (e.g. `vendor`) | First non-empty value wins |
| Total-like keys (`total`, `amount_due`, `grand_total`, `balance_due`, `amount_payable`) | Last non-empty value wins (grand total is typically on the final page) |

#### VLM Call

```python
client.chat.completions.create(
    model=settings.vlm_model,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": content},      # text or image parts
    ],
    max_tokens=settings.vlm_max_output_tokens,
    temperature=0,
)
```

`temperature=0` for deterministic output. `max_tokens` hard-caps the response to prevent budget overrun.

### Stage 4 — Full-Text Index Population

After extraction, the worker executes:
```sql
UPDATE documents
SET search_tsv = to_tsvector('english', :combined)
WHERE id = :doc_id
```
where `combined = original_filename + " " + extracted_text`. The GIN index on `search_tsv` makes all subsequent search queries fast.

### Error Handling in the Worker

| Scenario | Behaviour |
|---|---|
| Document not found on startup | `LookupError` raised → RQ retries (upload→commit race condition) |
| Text extraction crash | Sets `status=failed`, logs error, re-raises → RQ retry (max 3) |
| VLM crash / timeout | Logs warning, inserts `Extraction` row with `_error` field, continues to `completed` (document is still text-searchable) |
| VLM produces no data | Same: logs warning, document completes, no `extracted_data` |
| Max retries exceeded | `status=failed`, `error_message` stored, `ActivityEvent(processing_failed)` logged |

---

## 8. Search System

Search is a three-tier query — all executed in a single SQL statement, no extra services.

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

### Tier 3 — Trigram Filename Matching (typo tolerance)

```python
filename_match = func.word_similarity(q.lower(), func.lower(Document.original_filename)) >= 0.2
```

`pg_trgm` extension. `word_similarity` measures overlap of character 3-grams between the query and the filename. A threshold of `0.2` catches common typos (`"invioce"` matches `"invoice_2024.pdf"`). The threshold is embedded in the query — not a session GUC default — so it's always consistent.

### Ranking & Snippet

```python
rank = (
    func.coalesce(func.ts_rank_cd(Document.search_tsv, tsquery), 0.0)
    + func.coalesce(func.word_similarity(q.lower(), func.lower(Document.original_filename)), 0.0)
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
│   ├── layout.tsx                  # root layout (fonts, title)
│   ├── login/page.tsx              # login form
│   └── (app)/                      # authenticated route group
│       ├── layout.tsx              # wraps pages in AuthProvider + Sidebar
│       ├── dashboard/page.tsx
│       ├── upload/page.tsx
│       ├── documents/page.tsx
│       ├── documents/[id]/page.tsx
│       ├── search/page.tsx
│       └── settings/page.tsx
├── components/
│   ├── sidebar.tsx                 # navigation + storage meter + user row
│   └── status-badge.tsx            # coloured pill for document status
├── lib/
│   ├── api.ts                      # all API calls (typed, authenticated)
│   ├── auth.tsx                    # AuthProvider + useAuth() context
│   ├── supabase.ts                 # Supabase client singleton
│   ├── format.ts                   # formatBytes(), formatRelativeTime()
│   ├── utils.ts                    # cn() (clsx + tailwind-merge)
│   └── mock-data.ts                # mock data for settings page (not yet wired)
└── types/
    └── index.ts                    # all TypeScript types
```

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
- Drag-and-drop zone (HTML5 drag events) + file input fallback.
- Default document type selector (pill buttons): invoice, receipt, contract, report, letter, form, other.
- Per-file type override `<select>`.
- On submit: sequential `apiUploadDocument(formData)` per file; per-file status indicator.
- After 800 ms if all succeed: `router.push("/documents")`.

#### `/documents`
- Calls `apiDocuments({ status, type, sort, q, page })` on mount and on filter change.
- Pagination (page size 20). Sort options: date desc/asc, name asc/desc, size asc/desc.
- **3-second polling**: `setInterval` active while any row is in a non-terminal status (`queued`, `extracting_text`, `ocr_processing`, `ai_extraction`). Cleared when all rows reach `completed` or `failed`.
- Per-row actions: Download (calls `apiDownloadUrl`, opens in new tab), View (navigate to `/documents/:id`), Retry (calls `apiRetryDocument`).
- Bulk action: "Extract structured data" → `apiExtractMissing()`.

#### `/documents/:id`
- Calls `apiDocument(id)` on mount.
- **3-second polling** while status is not `completed` / `failed`.
- **Signed URL**: calls `apiDownloadUrl(id)` once on doc load → stores in `previewUrl` state.
- **Preview pane**: `<img>` for images; `<iframe>` for PDFs (browser built-in PDF viewer).
- **Three tabs:**
  - **Extracted Data**: renders `extractedData` JSONB as key-value pairs. Arrays (e.g. `line_items`) shown as card lists. Amount keys formatted as `MYR X.XX`. Confidence badge at top.
  - **Metadata**: flat table of all document fields (ID, MIME, pages, OCR confidence, AI confidence, storage key, etc.).
  - **Raw JSON**: collapsible interactive tree (`JsonValue` recursive component). Copy-to-clipboard button.
- Actions: Download, Retry (if failed), Re-run AI extraction.

#### `/search`
- Search triggers only on Enter key or Search button click (no debounced auto-search).
- `useEffect([submitted, typeFilter, dateFilter])` calls `apiSearch({ q, type, date })` on change.
- Result snippets rendered via `dangerouslySetInnerHTML` (server-generated `<mark>` tags from `ts_headline`).
- Filename highlights: client-side `highlight(text, query)` — simple case-insensitive substring match.
- Filter panel: document type pills, date dropdown (today / this week / this month / any time).
- Empty state shows "how search works" info box with suggested searches.

#### `/settings` (partially mocked)
- Five tabs: Organisation, Users & Access, API Keys, Security, Notifications.
- Organisation and Users tabs use `mockTenant` / `mockUsers` from `lib/mock-data.ts`.
- Not yet wired to live API (`apiOrganisation`, `apiUsers`, `apiApiKeys` are stubs).

### 10.4 TypeScript Types (`types/index.ts`)

```typescript
type ProcessingStatus = "queued" | "extracting_text" | "ocr_processing" | "ai_extraction" | "completed" | "failed"
type DocumentType = "invoice" | "receipt" | "contract" | "report" | "letter" | "form" | "other"
type UserRole = "admin" | "user"

interface Document {
  id: string; tenantId: string; filename: string; originalFilename: string;
  documentType: DocumentType; mimeType: string; sizeBytes: number;
  status: ProcessingStatus; uploadedBy: string; uploadedAt: string;
  processedAt: string | null; pageCount: number | null; hasTextLayer: boolean;
  ocrConfidence: number | null; confidence: number | null;
  extractedData: Record<string, unknown> | null; extractedText: string | null;
  tags: string[]; storageKey: string;
}

interface SearchResult {
  document: Document; score: number;
  snippet?: string;        // HTML string with <mark> tags from ts_headline
  matchedFields: string[]; // ["content", "filename"]
}
```

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
| `VLM_MAX_OUTPUT_TOKENS` | int | `256` | Tokens reserved for JSON response per call |
| `VLM_RENDER_DPI` | int | `120` | DPI for PDF → PNG rasterization in vision mode |
| `VLM_REQUEST_TIMEOUT` | float | `90.0` | HTTP timeout per VLM call (seconds) |
| `VLM_MAX_CHUNK_CALLS` | int | `10` | Hard cap on total VLM calls per document (1 header + up to 9 item chunks) |
| `VLM_MAX_PAGES` | int | `10` | Page ceiling per document in vision mode |
| `CONFIDENCE_THRESHOLD` | float | `0.7` | Minimum confidence to label an extraction `"accepted"` |
| `PROMOTE_AFTER_N` | int | `3` | Reserved: accepted extractions needed before template promotion |
| `MAX_UPLOAD_MB` | int | `50` | Maximum file size in MB (enforced at upload) |
| `CORS_ALLOW_ORIGINS` | string | `"http://localhost:3000"` | Comma-separated list of allowed CORS origins |
| `SENTRY_DSN` | string | `""` | Sentry error tracking DSN (configured but not yet wired in `main.py`) |
| `ENV` | string | `"development"` | Environment label; returned in `/api/health` |

**Frontend env vars** (`frontend/.env.local`):
| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key |
| `NEXT_PUBLIC_API_BASE_URL` | Backend API base URL (default: `http://localhost:8001/api`) |

---

## 12. Testing

Run all tests:
```bash
cd backend
pytest app/tests -v
```

Unit tests run offline (no DB, no Redis, no VLM). Integration tests require `ALEMBIC_DATABASE_URL` in `.env` and are automatically skipped if it is absent.

| File | Type | What it covers |
|---|---|---|
| `test_contract_camelcase.py` | Unit | Verifies `UserOut`, `TenantOut`, `MeOut` all fields have camelCase aliases matching `^[a-z][a-zA-Z0-9]*$` |
| `test_idp_pipeline.py` | Unit (mocked) | `run_extraction`: text-layer path (OCR not called), non-empty text, OCR fallback for scanned PDF, image MIME always OCR, multi-page mean confidence. I/O mocked via `sys.modules` patches |
| `test_ai_extraction.py` | Unit (mocked) | `extract_structured` text + vision mode, `render_page_images`, `_tolerant_parse` / `_repair_truncated_json`, skip path when no endpoint. Covers: valid JSON, no image parts in text mode, unknown type → `"other"`, confidence clamping, malformed JSON → error outcome, prose-wrapped JSON, flat fields without wrapper, two-phase chunking + merge (3 calls, line_items concatenated, totals last-wins), vision mode sends base64 image parts |
| `test_enqueue_on_upload.py` | Unit (mocked) | `create_documents` calls `enqueue_document` once per file; zero calls for empty list. `retry_document` calls `enqueue_document` once. `retry_document` raises HTTP 400 when doc not in `failed` state |
| `test_tenant_isolation.py` | Integration | Seeds 2 tenants. T1 GUC sees only T1's docs. T2's doc invisible under T1. Cross-tenant INSERT rejected by `WITH CHECK`. UPDATE on T2's doc under T1 → 0 rowcount. No GUC → 0 rows on all tables. Uses `SET LOCAL ROLE authenticated` |
| `test_search_service.py` | Integration | Seeds 1 tenant + 2 docs. FTS content match returns `<mark>` snippet. Trigram filename typo match. Ranking (denser term → higher score). Type filter. Empty query → empty result. No-match term → 0 results |
| `test_search_tenant_isolation.py` | Integration | Seeds 2 tenants with identical text content. T1 search sees only T1's doc |
| `test_idp_tenant_isolation.py` | Integration + Unit | `tenant_session(T1)` cannot `db.get` T2's document (RLS). UPDATE on T2's doc under T1 → 0 rowcount. `process_document` raises `LookupError` when doc invisible (mocked DB) |

---

## 13. Project File Structure

```
digital_ui/
├── CLAUDE.md                          # AI assistant instructions (this project)
├── read.md                            # This file
├── log/                               # Development logs by date
│   ├── 2026-06-05-backend-scaffold-progress.md
│   ├── 2026-06-08.md
│   ├── 2026-06-09.md
│   ├── 2026-06-10.md
│   ├── 2026-06-11.md
│   └── 2026-06-16.md
│
├── backend/
│   ├── pyproject.toml                 # Dependencies, ruff/black config, pytest config
│   ├── .env                           # Secrets — never committed
│   ├── app/
│   │   ├── main.py                    # FastAPI app: CORS, router mounts, /health
│   │   ├── worker.py                  # RQ worker entry: SimpleWorker/Worker + queue
│   │   │
│   │   ├── core/
│   │   │   ├── config.py              # Settings (pydantic-settings), @lru_cache singleton
│   │   │   ├── security.py            # verify_token(), TokenData, JWKS client
│   │   │   ├── deps.py                # get_current_user(), get_tenant_db(), require_admin()
│   │   │   ├── db.py                  # SQLAlchemy engine + SessionLocal
│   │   │   ├── tenant_context.py      # set_tenant() GUC, tenant_session() context manager
│   │   │   ├── storage.py             # Supabase Storage adapter (upload/download/signed URL)
│   │   │   └── camel.py               # CamelModel base class
│   │   │
│   │   ├── models/
│   │   │   ├── base.py                # DeclarativeBase, uuid_pk(), TimestampMixin
│   │   │   ├── tenant.py              # Tenant model
│   │   │   ├── user.py                # User model
│   │   │   ├── document.py            # Document model + STATUS_* constants
│   │   │   ├── document_type.py       # DocumentType model
│   │   │   ├── document_template.py   # DocumentTemplate model
│   │   │   ├── extraction.py          # Extraction model + METHOD_*/EXTRACTION_* constants
│   │   │   ├── processing_job.py      # ProcessingJob model + JOB_* constants
│   │   │   ├── activity_event.py      # ActivityEvent model + ACT_* constants
│   │   │   └── api_key.py             # ApiKey model
│   │   │
│   │   ├── modules/
│   │   │   ├── auth/
│   │   │   │   ├── router.py          # POST /auth/bootstrap, GET /auth/me
│   │   │   │   ├── service.py         # bootstrap(), _derive_tenant_name(), _supabase_admin()
│   │   │   │   └── schemas.py         # UserOut, TenantOut, MeOut
│   │   │   │
│   │   │   ├── files/
│   │   │   │   ├── router.py          # Upload, list, get, download, retry, extract routes
│   │   │   │   ├── service.py         # create_documents(), list_documents(), get_dashboard()...
│   │   │   │   └── schemas.py         # DocumentOut, DocumentListOut, DashboardOut...
│   │   │   │
│   │   │   ├── search/
│   │   │   │   ├── router.py          # GET /search
│   │   │   │   ├── service.py         # search_documents()
│   │   │   │   ├── query.py           # build_tsquery(), filename_match(), rank_expr(), snippet_expr()
│   │   │   │   └── schemas.py         # SearchResultOut, SearchListOut
│   │   │   │
│   │   │   └── idp/
│   │   │       ├── pipeline.py        # run_extraction(), run_ai_extraction(), ExtractionResult
│   │   │       ├── parsing.py         # open_pdf(), extract_text_layer(), rasterize_page()
│   │   │       ├── ocr.py             # ocr_image(), RapidOCR singleton
│   │   │       ├── extraction.py      # extract_structured(), _extract_two_phase(), _merge_extractions()
│   │   │       ├── jobs.py            # process_document(), ai_extract_document()
│   │   │       └── queue.py           # enqueue_document(), enqueue_ai_extraction()
│   │   │
│   │   ├── migrations/
│   │   │   ├── env.py                 # Alembic config (loads .env, NullPool, metadata)
│   │   │   └── versions/
│   │   │       ├── 0001_initial_tables.py
│   │   │       ├── 0002_rls_policies.py
│   │   │       ├── 0003_seed_system_document_types.py
│   │   │       ├── 0004_grant_app_roles.py
│   │   │       └── 0005_fix_rls_nullif.py
│   │   │
│   │   └── tests/
│   │       ├── conftest.py                        # loads .env for integration tests
│   │       ├── test_contract_camelcase.py
│   │       ├── test_idp_pipeline.py
│   │       ├── test_ai_extraction.py
│   │       ├── test_enqueue_on_upload.py
│   │       ├── test_tenant_isolation.py
│   │       ├── test_search_service.py
│   │       ├── test_search_tenant_isolation.py
│   │       └── test_idp_tenant_isolation.py
│
└── frontend/
    ├── package.json
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── app/
    │   ├── page.tsx                   # redirect to /login
    │   ├── layout.tsx                 # root layout (fonts, <html>)
    │   ├── login/page.tsx             # Supabase sign-in + bootstrap
    │   └── (app)/
    │       ├── layout.tsx             # AuthProvider + Sidebar wrapper
    │       ├── dashboard/page.tsx
    │       ├── upload/page.tsx
    │       ├── documents/page.tsx
    │       ├── documents/[id]/page.tsx
    │       ├── search/page.tsx
    │       └── settings/page.tsx
    ├── components/
    │   ├── sidebar.tsx
    │   └── status-badge.tsx
    ├── lib/
    │   ├── api.ts
    │   ├── auth.tsx
    │   ├── supabase.ts
    │   ├── format.ts
    │   ├── utils.ts
    │   └── mock-data.ts
    └── types/
        └── index.ts
```

---

---

# Part 2 — Plain-English Guide

---

## 14. What is DataWiz?

DataWiz is a **cloud document archive for businesses**. Think of it like a smart filing cabinet that lives on the internet.

You upload your business documents — invoices, receipts, contracts, reports — and the system:
- **Stores them securely** in the cloud
- **Reads them automatically** and pulls out key information (who sent the invoice, how much it's for, what items were purchased)
- **Makes everything searchable** — search by a word from inside the document, the filename, or even a misspelled filename

It's built for **small businesses in Malaysia** (PDPA-aware) that deal with a lot of paperwork and want it organised and easy to find.

**The biggest design goal: keep costs low.** The system does as much work as possible using free or cheap methods, and only uses the expensive AI when absolutely necessary. Most documents are processed at near-zero cost.

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

A background worker picks up the job from the queue and processes the document through 4 stages:

**Stage 1 — Read the text (FREE)**
If the PDF already contains text (like a document you typed or a computer-generated invoice):
- The system extracts the text directly. This is instant and costs nothing.
- This is how most modern PDFs work.

**Stage 2 — OCR (cheap, if needed)**
If the PDF is a scan or a photo (like photographing a paper invoice):
- The system can't just "read" it — the text is baked into the image
- It uses OCR (Optical Character Recognition) — software that reads text from images
- This runs on the server's CPU — no expensive GPU needed
- The RapidOCR engine used here is open-source and free

**Stage 3 — AI structured extraction**
After getting the text, the system sends it to an AI model (a Visual Language Model running on a GPU server):
- **Phase 1**: Ask the AI for the document's header information — vendor name, invoice number, date, total amount, currency, buyer name
- **Phase 2**: Ask the AI to extract every single line item (product code, description, quantity, unit price, amount)

The AI's output is automatically organised into a structured format you can see in the "Extracted Data" tab.

**Stage 4 — Make it searchable**
The document's text is added to the search index. Now you can find this document by searching for any word that appears in it.

### Step 4: You view and search your documents

- The Documents page lists all your uploaded documents and their processing status
- The Document Viewer shows the original file alongside the extracted data
- The Search page lets you find documents by content, filename, or even a slightly misspelled filename

### What "tenant isolation" means (simply)

DataWiz is a **multi-tenant** system — many companies use the same software, but each company's data is completely separate. It's like a building with many apartments: you have your own apartment (tenant), and no one else can walk into it. The locks are enforced at the database level, not just the app level — even if there were a bug in the app code, the database would still refuse to show you someone else's data.

---

## 16. What's Already Built

### Authentication & Account Setup ✅
- Sign in with email and password
- Automatic first-login setup (no manual admin configuration needed)
- Admin and user roles
- Secure JWT token verification (two algorithm types supported)

### Document Upload ✅
- Upload PDF, scanned PDF, JPEG, PNG, WebP, TIFF
- File size limit: 50 MB per file
- Multiple files at once
- Assign a document type at upload (invoice, receipt, contract, etc.)
- Secure cloud storage — no file bytes ever stored in the database

### Automatic Text Extraction ✅
- Digital PDFs: text extracted instantly, no AI cost
- Scanned PDFs and images: CPU-based OCR (RapidOCR)
- OCR confidence score stored for quality tracking
- Full-text search index populated automatically

### AI Structured Extraction ✅
- Two-phase VLM extraction (header + line items)
- Works on digital PDFs (text mode) and scanned documents (vision mode)
- Handles large multi-page invoices by splitting into chunks and merging results
- Recovers from truncated AI output (truncation repair algorithm)
- Confident extractions marked `accepted`; low-confidence marked `low_confidence`
- Every extraction attempt logged in the `extractions` table for audit

### Document Library ✅
- Paginated document list with sort and filter options
- Status filtering (queued, processing, completed, failed)
- Document type filtering
- Real-time status updates (page polls every 3 seconds while processing)

### Document Viewer ✅
- Inline preview: PDFs open in browser's built-in viewer; images displayed directly
- Extracted Data tab: key-value pairs with line items as cards, confidence score
- Metadata tab: all technical fields
- Raw JSON tab: interactive collapsible tree with copy-to-clipboard
- Retry button for failed documents
- Re-run AI extraction button for completed documents without extracted data

### Search ✅
- Search by words inside the document (full-text search)
- Search by partial words — "inv" finds "invoice"
- Search by filename with typos — "invioce" finds "invoice_2024.pdf"
- Search results show highlighted excerpts with matching words in yellow
- Filter by document type and date uploaded

### Dashboard ✅
- Total documents count, processing status breakdown
- Storage usage gauge (used vs. 10 GB limit)
- Recent documents list
- Activity feed (uploads, completions, failures, downloads)

### Multi-Tenancy & Security ✅
- Every company's data completely isolated at the database level (Row-Level Security)
- Signed URLs for file access (expire after 5 minutes)
- All API endpoints tenant-scoped
- 8 automated tests proving tenant isolation

---

## 17. What's Coming Next

These features are planned but not yet built. They will not be added without explicit decision.

### Near-term (Milestone F onwards)

| Feature | Description |
|---|---|
| **Better AI extraction quality** | Upgrade to a larger VLM model (Qwen2.5-VL-7B) once more GPU budget is available — better field accuracy, more line items captured |
| **Settings page — live data** | Wire the Organisation and Users tabs to real API calls (currently shows mock data) |
| **More document types** | Dedicated extraction for receipts and contracts (currently handles invoices best) |
| **API keys** | Allow programmatic access to the archive (backend model already built) |

### Medium-term (Phase 2 / post-MVP)

| Feature | Description |
|---|---|
| **Self-learning templates** | The system notices that documents from the same vendor always look the same. After 3 successful extractions, it "promotes" that layout to a template and extracts future documents deterministically (no AI cost) |
| **Analytics dashboard** | Charts showing extraction quality over time, document volume trends, cost savings from the deterministic path |
| **Exception review UI** | A queue of low-confidence extractions for a human to review and correct. Each correction becomes a new extraction rule |
| **Semantic search (pgvector)** | Find documents by meaning, not just keywords — e.g. "find invoices for cleaning services" even if the word "cleaning" doesn't appear |
| **Email ingestion** | Forward invoices to a dedicated email address; system auto-archives them |

### Deliberately out of scope (for MVP)

These will not be built unless explicitly requested:
- Microservices or separate containers per feature
- Elasticsearch or external search cluster
- Cross-encoder reranking for search
- Schema-per-tenant database isolation (current RLS approach is sufficient and free)
- Mobile app
- Multi-region deployment
- SSO / SAML enterprise login
- Batch LLM API calls

---

*Last updated: 2026-06-18*
*Milestones complete: A (Auth), B (Upload + Storage), C (IDP pipeline), D (Search), E (VLM extraction)*
