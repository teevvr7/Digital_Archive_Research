# DataWiz Digital Archive — Complete System Status & Technical Reference
**Date of Record: 15 July 2026**

---

## Table of Contents

**Part 1 — Technical Reference**
1. [Project Overview](#1-project-overview)
2. [System Architecture & Data Flows](#2-system-architecture--data-flows)
3. [Technology Stack](#3-technology-stack)
4. [Database Schema (All 16 Tables)](#4-database-schema)
5. [Security & Multi-Tenancy (Row Level Security)](#5-security--multi-tenancy)
6. [Backend API Endpoint Reference](#6-backend-api-endpoint-reference)
7. [IDP Ingestion Pipeline Stages](#7-idp-ingestion-pipeline-stages)
8. [Search & Typo-Tolerance System](#8-search--typo-tolerance-system)
9. [Queue & Background Worker](#9-queue--background-worker)
10. [Frontend Application Structure](#10-frontend-application-structure)
11. [Configuration Reference (Environment Variables)](#11-configuration-reference)
12. [Testing Framework & Test Suite](#12-testing-framework--test-suite)
13. [Project Directory Layout](#13-project-directory-layout)

**Part 2 — System Operations Guide**
14. [What is DataWiz? (High-Level Summary)](#14-what-is-datawiz)
15. [How Data Flows - Step by Step](#15-how-data-flows---step-by-step)
16. [Current Implemented Features (What's Already Built)](#16-current-implemented-features)
17. [Planned Roadmap & Future Features](#17-planned-roadmap--future-features)

---

# Part 1 — Technical Reference

---

## 1. Project Overview

**DataWiz Digital Archive** is a secure, multi-tenant SaaS document archive system equipped with an Intelligent Document Processing (IDP) ingestion pipeline. It allows business users to upload PDFs, scanned papers, and document images; the system securely stores them, automatically extracts raw text and key structured fields, links entities (tags and correspondents), and makes the text instantly searchable.

### Core Design Principles
* **The 10–15% AI Exception Rule**: Deterministic code (direct digital text reading, layout templates, local/remote OCR, search indexes) handles ~85–90% of documents. The VLM AI layer (Qwen-VL) is only called when cheaper paths fail or are unavailable.
* **Cost Cascading (Cheapest-First)**:
  1. *Digital PDF (with text layer)*: Read text natively via PyMuPDF — **Instant & Free**.
  2. *Scan/Image Layout Template match*: If the layout fingerprint matches a tenant template, extract fields deterministically via bounding-box coordinate selectors — **Cheap & Local**.
  3. *Scan/Image OCR fallback*: Run local CPU-bound RapidOCR or remote PaddleOCR — **Cheap & No GPU**.
  4. *Structured data parse*: Remote GPU-bound Qwen-VL model — **Only on completed text ingestion**.
  5. *Search index query*: Scoped full-text and trigram indexing inside the primary PostgreSQL database — **Zero external search clusters (no Elasticsearch/Qdrant)**.
* **Infrastructure Budget Goal**: Zero to near-zero fixed costs (utilising Supabase free tier for DB/Auth/Storage, and running vLLM servers on-demand or on shared GPU environments).

---

## 2. System Architecture & Data Flows

The application separates concerns across the Next.js frontend, FastAPI web API, Redis Queue background workers, remote Paddle/Qwen VLM AI nodes, and Supabase cloud resources.

```
                  ┌──────────────────────────────────────────────┐
                  │          Browser (Next.js SPA)               │
                  │  JWT obtained from Supabase Auth             │
                  │  Passed in header: Bearer <JWT>              │
                  └──────────────────────┬───────────────────────┘
                                         │ HTTPS / JSON
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │            FastAPI Backend (:8001)           │
                  │  Enforces: verify_token(JWT)                 │
                  │  Database GUC: app.current_tenant = tenant_id│
                  │  Enforces RLS at the Database transaction    │
                  └──────────────┬────────────────┬──────────────┘
                                 │                │ Enqueue Job (Redis)
                                 ▼                ▼
┌─────────────────────────────────┐   ┌──────────────────────────┐
│  Supabase PostgreSQL Database   │   │    Redis Queue (idp)     │
│                                 │   └───────────┬──────────────┘
│  Tables (RLS active):           │               │ Job Worker
│  - tenants, users, documents    │               ▼
│  - tags, correspondents         │   ┌──────────────────────────┐
│  - custom_fields, values        │   │    RQ Background Worker  │
│  - templates, extractions       │   │  (python -m app.worker)  │
│  - saved_views, ai_usage        │   │                          │
│                                 │   │  - PyMuPDF text reader   │
│  Indexes:                       │◄──│  - RapidOCR/PaddleOCR    │
│  - GIN search_tsv               │   │  - Dynamic VLM request   │
│  - Trigram filename             │   │  - Rules Engine Matcher  │
│  - GIN jsonb path               │   └───────────┬──────────────┘
└─────────────────────────────────┘               │
                                                  │ API / Base64 Data
                                                  ▼
                                      ┌──────────────────────────┐
                                      │ Remote AI Server (Paddle)│
                                      │ - PP-DocLayoutV3 OCR     │
                                      │ - Qwen3-VL-4B-Instruct   │
                                      └──────────────────────────┘
```

### Ingestion Request Lifecycle
1. **Upload Request**: The browser issues a multi-part `POST` to `/api/documents`, transferring raw files and optional template IDs.
2. **Metadata Writing**: The API verifies the JWT, sets the tenant transaction GUC, uploads the file to the S3 bucket (`Supabase Storage`), inserts `Document` and `ProcessingJob` rows, and logs an `activity_event`.
3. **Queue Ingestion**: The API enqueues `process_document(doc_id, tenant_id)` in Redis Queue (`rq`) and returns a listing array immediately.
4. **Worker Processing**:
   * *Stage 1*: The worker retrieves file bytes from storage and attempts digital text reading via `PyMuPDF`.
   * *Stage 2*: If the text layer is empty or sparse, the worker runs OCR using the `RapidOCR` client or requests remote `PaddleOCR`.
   * *Stage 3*: Remaps and extracts structured JSON fields. If a template ID is matched or resolved by layout fingerprint, it extracts data deterministically. Otherwise, it calls the remote `Qwen-VL` model.
   * *Stage 4*: Link tagging and correspondents via pattern-matching rules, builds the search index (`search_tsv`), and updates status to `completed`.
5. **UI Polling**: The frontend page polls the single document status every 3 seconds, rendering the loaded data fields as soon as status becomes `completed`.

---

## 3. Technology Stack

### Backend Stack
* **Python (>=3.11)**: Core runtime.
* **FastAPI (>=0.115)**: Web API layer.
* **Uvicorn (>=0.30)**: ASGI server.
* **SQLAlchemy (>=2.0)**: ORM layer, utilizing direct transactions and GUC Gated variables.
* **Alembic (>=1.13)**: Database schema migration tracker.
* **psycopg3 (>=3.2)**: Modern Postgres client driver (with prepared statements disabled for Supabase transaction pool compatibility).
* **Redis & RQ (>=1.16)**: Redis-backed task queuing framework.
* **Supabase Python SDK**: Storage file integrations, Auth validation, and admin actions.

### Remote AI Server Stack
* **PaddlePaddle & PP-DocLayoutV3**: Used for robust PDF page layout analysis and text region zoning.
* **vLLM Engine**: Serves `Qwen3-VL-4B-Instruct` model dynamically with OpenAI-compatible API parameters.
* **Eager Initialization Lifecycle**: Models are eagerly instantiated at server startup to secure single VRAM allocations and avoid thread-safety duplicates.

### Frontend Stack
* **Next.js (16.2.7) / React (19.2.4)**: Dynamic single-page app structure.
* **Supabase JS Client SDK**: JWT session handling and storage.
* **TailwindCSS**: Premium responsive styles.
* **Lucide React**: Vector SVG icons.

---

## 4. Database Schema

All tables enforce tenant-level isolation via Postgres Row-Level Security (RLS) policies based on the session variable `app.current_tenant`.

### 4.1 Schema Entity Definitions (All 16 Tables)

#### `tenants`
*Root tenant configuration entity.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `name` | VARCHAR | No | Company name derived from email domain |
| `plan` | VARCHAR | No | Default: `"starter"` |
| `storage_used_bytes` | BIGINT | No | Default: `0` |
| `storage_limit_bytes`| BIGINT | No | Default: `10 GB` |
| `llm_monthly_token_cap`| INTEGER| Yes | Monthly cap limit; NULL uses global default |
| `created_at` | TIMESTAMPTZ | No | `now()` |

#### `users`
*System users associated with a tenant.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key (matches Supabase Auth `sub`) |
| `tenant_id` | UUID | No | FK -> `tenants.id` (CASCADE) |
| `email` | VARCHAR | No | User login email (Unique) |
| `name` | VARCHAR | No | Display name |
| `role` | VARCHAR | No | `"admin"` or `"user"`; Default: `"user"` |
| `avatar_initials` | VARCHAR | No | 1-2 letters derived from name |
| `created_at` | TIMESTAMPTZ | No | |
| `last_login_at` | TIMESTAMPTZ | Yes | Updated on session bootstrap |

#### `documents`
*Central file archive records.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `tenant_id` | UUID | No | FK -> `tenants.id` (CASCADE) |
| `filename` | VARCHAR | No | Cleaned storage display filename |
| `original_filename` | VARCHAR | No | Raw file name as uploaded |
| `mime_type` | VARCHAR | No | MIME type |
| `size_bytes` | BIGINT | No | |
| `storage_key` | VARCHAR | No | `"{tenant_id}/docs/{doc_id}.{ext}"` |
| `status` | VARCHAR | No | Default: `"queued"` |
| `error_message` | TEXT | Yes | Limit 2000 chars; populated on failure |
| `document_type` | VARCHAR | No | Default: `"other"` |
| `document_type_id` | UUID | Yes | FK -> `document_types.id` (SET NULL) |
| `template_id` | UUID | Yes | FK -> `document_templates.id` (SET NULL) |
| `page_count` | INTEGER | Yes | Processed page quantity |
| `has_text_layer` | BOOLEAN | No | Default: `false` |
| `ocr_used` | BOOLEAN | No | Default: `false` |
| `ocr_engine` | VARCHAR | Yes | `"paddleocr" \| "rapidocr" \| null` |
| `ocr_confidence` | REAL | Yes | Mean OCR character score |
| `vlm_model` | VARCHAR | Yes | Model tag identifier utilized |
| `extraction_method` | VARCHAR| Yes | `"vlm" \| "deterministic" \| "manual"` |
| `extracted_data` | JSONB | Yes | Structured parsing keys |
| `extracted_text` | TEXT | Yes | Raw content string |
| `confidence` | REAL | Yes | Model extraction score |
| `search_tsv` | TSVECTOR | Yes | Full-text query vectors |
| `has_thumbnail` | BOOLEAN | No | Default: `false` |
| `thumbnail_key` | VARCHAR | Yes | `"{tenant_id}/thumbnails/{doc_id}.png"` |
| `checksum` | VARCHAR | Yes | SHA-256 duplicate validator |
| `title` | VARCHAR | Yes | Document title |
| `document_date` | DATE | Yes | Date on the document |
| `correspondent_id` | UUID | Yes | FK -> `correspondents.id` (SET NULL) |
| `deleted_at` | TIMESTAMPTZ | Yes | Soft-delete timestamp; non-null is in trash |
| `uploaded_by` | UUID | No | FK -> `users.id` (RESTRICT) |
| `uploaded_at` | TIMESTAMPTZ | No | `now()` |
| `processed_at` | TIMESTAMPTZ | Yes | Populated on success |

#### `document_types`
*Catalogs document type schemas.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `tenant_id` | UUID | Yes | NULL = Global system type |
| `name` | VARCHAR | No | e.g. `"invoice"`, `"receipt"` |
| `description` | TEXT | Yes | |
| `json_schema` | JSONB | Yes | Soft validator fields structure |
| `is_system` | BOOLEAN | No | Default: `false` |
| `extraction_method` | VARCHAR| No | Default: `"paddle_qwen"` |
| `created_at` | TIMESTAMPTZ | Yes | |

#### `document_templates`
*Learned extraction parameters for deterministic cascades.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `tenant_id` | UUID | No | FK -> `tenants.id` (CASCADE) |
| `document_type_id` | UUID | No | FK -> `document_types.id` (CASCADE) |
| `name` | VARCHAR | No | Template identifier name |
| `fingerprint` | VARCHAR | No | Layout fingerprint hash |
| `field_mappings` | JSONB | No | Coordinate extraction rules |
| `status` | VARCHAR | No | `"candidate" \| "promoted" \| "disabled"` |
| `examples_count` | INTEGER | No | Increment count on manual confirmation |
| `confidence` | REAL | Yes | |
| `version` | INTEGER | No | Default: `1` |
| `extraction_method` | VARCHAR| No | Default: `"default"` |
| `is_default` | BOOLEAN | No | Default: `false` |
| `use_image` | BOOLEAN | No | Default: `false` |
| `use_ocr` | BOOLEAN | No | Default: `true` |
| `sample_document_id` | UUID | Yes | FK -> `documents.id` (SET NULL) |
| `created_at` | TIMESTAMPTZ | No | `now()` |
| `updated_at` | TIMESTAMPTZ | No | `now()` (onupdate trigger) |

#### `extractions`
*Audit ledger log of VLM parsing runs.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `tenant_id` | UUID | No | FK -> `tenants.id` (CASCADE) |
| `document_id` | UUID | No | FK -> `documents.id` (CASCADE) |
| `template_id` | UUID | Yes | FK -> `document_templates.id` (SET NULL) |
| `method` | VARCHAR | No | `"vlm" \| "deterministic" \| "manual"` |
| `model_name` | VARCHAR | Yes | Model code tag |
| `output` | JSONB | Yes | Saved attributes JSON |
| `confidence` | REAL | Yes | Extraction score |
| `status` | VARCHAR | No | `"accepted" \| "low_confidence" \| "corrected"` |
| `created_at` | TIMESTAMPTZ | No | |

#### `processing_jobs`
*Tracks background processing state.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `tenant_id` | UUID | No | FK -> `tenants.id` (CASCADE) |
| `document_id` | UUID | No | FK -> `documents.id` (CASCADE) |
| `status` | VARCHAR | No | `"queued" \| "running" \| "completed" \| "failed"` |
| `stage` | VARCHAR | Yes | `"text_extraction" \| "ocr_processing" \| "ai_extraction"` |
| `attempts` | INTEGER | No | Increment value on retry attempts |
| `error` | TEXT | Yes | Worker error traces |
| `enqueued_at` | TIMESTAMPTZ | No | `now()` |
| `started_at` | TIMESTAMPTZ | Yes | |
| `finished_at` | TIMESTAMPTZ | Yes | |
| `duration_ms` | INTEGER | Yes | Wall-clock execution milliseconds |

#### `activity_events`
*Append-only user activity logs.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `tenant_id` | UUID | No | FK -> `tenants.id` (CASCADE) |
| `type` | VARCHAR | No | `"upload" \| "processing_complete" \| "processing_failed" \| "search" \| "download" \| "user_added" \| "edit" \| "trash" \| "restore" \| "permanent_delete"` |
| `document_id` | UUID | Yes | FK -> `documents.id` (SET NULL) |
| `document_name` | VARCHAR | Yes | Captured document filename |
| `user_id` | UUID | Yes | FK -> `users.id` (SET NULL) |
| `user_name` | VARCHAR | No | Captured user name |
| `timestamp` | TIMESTAMPTZ | No | `now()` |
| `meta` | TEXT | Yes | Context strings |

#### `api_keys`
*B-tree hashed API keys.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `tenant_id` | UUID | No | FK -> `tenants.id` (CASCADE) |
| `name` | VARCHAR | No | Display name |
| `prefix` | VARCHAR | No | e.g. `"dw_abc123"` |
| `hashed_key` | VARCHAR | No | SHA-256 key hash |
| `created_at` | TIMESTAMPTZ | No | |
| `last_used_at` | TIMESTAMPTZ | Yes | |

#### `ai_usage`
*API consumption ledger for budget verification.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `tenant_id` | UUID | No | FK -> `tenants.id` (CASCADE) |
| `document_id` | UUID | Yes | FK -> `documents.id` (SET NULL) |
| `model_name` | VARCHAR | Yes | VLM model code |
| `prompt_tokens` | INTEGER | No | Default: `0` |
| `completion_tokens`| INTEGER| No | Default: `0` |
| `total_tokens` | INTEGER | No | Default: `0` |
| `created_at` | TIMESTAMPTZ | No | `now()` |

#### `tags`
*Per-tenant persistent tags.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `tenant_id` | UUID | No | FK -> `tenants.id` (CASCADE) |
| `name` | TEXT | No | Display label |
| `color` | TEXT | No | Hex color code (default: `#6B7280`) |
| `match` | TEXT | No | Match rule matching criteria |
| `matching_algorithm`| TEXT| No | `"none" \| "any" \| "all" \| "literal" \| "regex"`; default: `"any"` |
| `is_insensitive` | BOOLEAN | No | Case insensitive match flag |
| `is_inbox_tag` | BOOLEAN | No | Inbox sorting indicator |
| `created_at` | TIMESTAMPTZ | No | `now()` |

*Constraints: Unique on `(tenant_id, name)`.*

#### `document_tags`
*M2M join mapping documents to tags.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `tenant_id` | UUID | No | FK -> `tenants.id` (CASCADE) |
| `document_id` | UUID | No | FK -> `documents.id` (CASCADE) |
| `tag_id` | UUID | No | FK -> `tags.id` (CASCADE) |

*Constraints: Unique on `(document_id, tag_id)`.*

#### `correspondents`
*Sender/Vendor rules classification ledger.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `tenant_id` | UUID | No | FK -> `tenants.id` (CASCADE) |
| `name` | TEXT | No | Vendor name |
| `match` | TEXT | No | Match rules criteria |
| `matching_algorithm`| TEXT| No | `"none" \| "any" \| "all" \| "literal" \| "regex"`; default: `"any"` |
| `is_insensitive` | BOOLEAN | No | Case insensitivity match flag |
| `created_at` | TIMESTAMPTZ | No | `now()` |

*Constraints: Unique on `(tenant_id, name)`.*

#### `custom_fields`
*Flexible catalog fields for custom metadata.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `tenant_id` | UUID | No | FK -> `tenants.id` (CASCADE) |
| `name` | TEXT | No | Field label name |
| `field_type` | TEXT | No | `"text" \| "number" \| "date" \| "boolean" \| "select"` |
| `options` | JSONB | No | Dropdown items array list |
| `position` | INTEGER | No | Sort order position |
| `created_at` | TIMESTAMPTZ | No | `now()` |

#### `document_field_values`
*Per-document custom metadata field values.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `tenant_id` | UUID | No | FK -> `tenants.id` (CASCADE) |
| `document_id` | UUID | No | FK -> `documents.id` (CASCADE) |
| `field_id` | UUID | No | FK -> `custom_fields.id` (CASCADE) |
| `value` | JSONB | Yes | Typed metadata cell value |

*Constraints: Unique on `(document_id, field_id)`.*

#### `saved_views`
*Persistent filter query state presets.*
| Column | Type | Nullable | Notes / Default |
|---|---|---|---|
| `id` | UUID | No | Primary Key |
| `tenant_id` | UUID | No | FK -> `tenants.id` (CASCADE) |
| `name` | TEXT | No | Display label name |
| `filter_state` | JSONB | No | Query selector parameters dict |
| `is_default` | BOOLEAN | No | Sets default on workspace dashboard open |
| `created_at` | TIMESTAMPTZ | No | `now()` |

---

### 4.2 Database Indexes

The system maintains 22 active indexes for fast querying:

* `ix_documents_search_tsv`: `GIN` on `documents.search_tsv` (Full-Text query matches).
* `ix_documents_filename_trgm`: `GIN` with `gin_trgm_ops` on `lower(original_filename)` (Typo-tolerant filename matching).
* `ix_documents_extracted_gin`: `GIN` with `jsonb_path_ops` on `extracted_data` (Attributes lookup).
* `ix_documents_tenant_id`: `B-tree` on `documents.tenant_id` (Tenant filtering).
* `ix_documents_deleted_at`: `B-tree` on `documents.deleted_at` (Trash filtering).
* `ix_document_tags_doc_id`: `B-tree` on `document_tags.document_id`.
* `ix_document_tags_tag_id`: `B-tree` on `document_tags.tag_id`.
* `ix_custom_fields_tenant_id`: `B-tree` on `custom_fields.tenant_id`.
* `ix_document_field_values_doc_id`: `B-tree` on `document_field_values.document_id`.
* `ix_ai_usage_tenant_id`: `B-tree` on `ai_usage.tenant_id`.
* `ix_ai_usage_tenant_created`: `B-tree` on `(tenant_id, created_at DESC)`.

---

### 4.3 Alembic Database Migrations

* **`0001`**: `0001_initial_tables.py` - Sets up the original 9 tables and `pgcrypto`/`pg_trgm` extensions.
* **`0002`**: `0002_rls_policies.py` - Configures `ROW LEVEL SECURITY` across tables.
* **`0003`**: `0003_seed_system_document_types.py` - Seeds core types (`invoice`, `receipt`, etc.).
* **`0004`**: `0004_grant_app_roles.py` - Sets permissions for application role context swaps.
* **`0005`**: `0005_fix_rls_nullif.py` - Hardens policies to fail closed if the tenant GUC is unset.
* **`0006`**: `0006_ai_usage_budget.py` - Creates `ai_usage` token-ledger tracking.
* **`0007`**: `0007_universal_ingestion.py` - Adds ingestion metadata keys (`title`, `checksum`, etc.).
* **`0008`**: `0008_soft_delete.py` - Installs `deleted_at` column for the Trash system.
* **`0009`**: `0009_tags_correspondents.py` - Creates `tags` and `correspondents` structures.
* **`0010`**: `0010_custom_fields.py` - Creates `custom_fields` and values mapping tables.
* **`0011`**: `0011_saved_views.py` - Creates `saved_views` filtering template table.
* **`eebe53429cbf`**: `eebe53429cbf_add_extraction_method_column.py` - Adds `extraction_method` logging.
* **`62a974d876f0`**: `62a974d876f0_add_multi_template_and_modality_columns.py` - Adds worker status tracking indicators.
* **`2f0fd6e40db5`**: `2f0fd6e40db5_remove_layout_fingerprint_and_tags_.py` - Cleans up and drops deprecated array structures.

---

## 5. Security & Multi-Tenancy

DataWiz enforces multi-tenant boundary checks natively inside the PostgreSQL engine via GUC parameters.

### 5.1 Token Verification
* Standard endpoints require an authorization token verified by `verify_token` in `app/core/security.py`.
* Symmetric encryption (`HS256`) uses `SUPABASE_JWT_SECRET`.
* Asymmetric encryption (`RS256` / `ES256`) fetches key identifiers dynamically from `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` using a cached lazy-loaded client.

### 5.2 RLS Execution GUC Scope
1. Every API call opens a transaction block (`get_tenant_db` dependency).
2. Runs: `SET LOCAL app.current_tenant = '{tenant_id}'`.
3. The GUC resets automatically on transaction commit or rollback.
4. RLS policies evaluate: `USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)`. If the GUC is empty, `NULLIF` evaluates to `NULL` and queries fail closed (returns 0 rows).

---

## 6. Backend API Endpoint Reference

All endpoints return camelCase JSON keys. Authenticated routes require `Authorization: Bearer <JWT>`.

### 6.1 Authentication & Bootstrap
* `POST /api/auth/bootstrap` — Initializes user profile & tenant ID metadata at first login.
* `GET /api/auth/me` — Fetches current user profile.

### 6.2 Documents Ingestion & Library
* `POST /api/documents` — Multipart file upload (optional template ID parameter).
* `GET /api/documents` — Paginated list of documents (filters: `status`, `type`, `tag_id`, `correspondent_id`, `date_from`, `date_to`, `sort`, `page`).
* `GET /api/documents/{id}` — Fetches single document record.
* `PATCH /api/documents/{id}` — Performs manual override edits on custom fields/extracted keys.
* `GET /api/documents/{id}/download` — Generates a signed object storage access URL (expire in 5 minutes).
* `POST /api/documents/{id}/retry` — Re-queues a failed document.
* `POST /api/documents/{id}/extract` — Re-runs structured extraction.

### 6.3 Metadata & Tags Catalog
* `GET /api/tags` | `POST /api/tags` | `PATCH /api/tags/{id}` | `DELETE /api/tags/{id}` — Tags catalog CRUD.
* `GET /api/correspondents` | `POST /api/correspondents` | `PATCH /api/correspondents/{id}` | `DELETE /api/correspondents/{id}` — Correspondents catalog CRUD.
* `GET /api/metadata/fields` | `POST /api/metadata/fields` — Custom fields configuration metadata catalog.
* `GET /api/views` | `POST /api/views` — Saved filter preset views.

### 6.4 Bulk Operations
* `POST /api/documents/bulk-trash` — Bulk soft-deletes documents.
* `POST /api/documents/bulk-tag` — Mass tags/untags documents.
* `POST /api/documents/bulk-set-type` — Bulk document type overrides.

### 6.5 Spreadsheet Export (/api/export)
* `GET /api/export/meta` — Dropdowns meta loader (document types and promoted template options).
* `POST /api/export/fields` — Scans active templates or types mapping schema to fetch selectable column tags.
* `POST /api/export/spreadsheet` — Generates accounting data. Query param `?format=preview` returns first 50 rows in JSON; `?format=csv` triggers a streaming download.

---

## 7. IDP Ingestion Pipeline Stages

The ingestion pipeline handles documents asynchronously via background Redis Queue workers.

### Stage 1 — Text Extraction
* Checks for embedded text using `PyMuPDF`.
* If non-whitespace character count >= `max(16, 8 * page_count)`, text is extracted directly — **Digital Read (Slate badge)**.
* Otherwise, pages are rasterized to PNGs and passed to OCR.

### Stage 2 — OCR (Optical Character Recognition)
* For scans or images, uses `PaddleOCR` (GPU remote studio) or runs local `RapidOCR` fallback.
* Computes mean confidence scores to log on the metadata record.

### Stage 3 — VLM Structured Extraction
* **Token Budget Math**: Context limits are calculated dynamically to avoid budget overflows:
  `input_budget = max(256, max_model_len - output_tokens - prompt_overhead - safety_margin)`
* **Deterministic Cascade**: Matches the layout fingerprint against promoted tenant templates. If found, extracts values deterministically via bounding-box coordinate rules without calling the AI.
* **Two-Phase VLM Request**: If no template matches:
  * *Phase 1 (Header)*: Queries VLM for primary meta fields (Vendor, totalAmount, invoiceNumber, date).
  * *Phase 2 (Line Items)*: Iterates through text chunks to parse granular arrays of items.
* **JSON Repair Tracker**: A stack-based bracket tracker parses and repairs truncated JSON objects before merge completion.

### Stage 4 — Search Indexing
* Updates the document's `search_tsv` vector with `to_tsvector('english', original_filename + " " + extracted_text)`.

---

## 8. Search & Typo-Tolerance System

A single SQL query evaluates matches across three tiers:
1. **Full-Text Match**: Evaluates `search_tsv @@ websearch_to_tsquery('english', query)`.
2. **Fuzzy Phrase Match**: Breaks search inputs into wildcards (`tok:*`) for autocomplete-as-you-type compatibility.
3. **Trigram Filename Similarity**: Uses `pg_trgm`'s `word_similarity()` with a threshold of `0.2` to catch typos (e.g. searching `"invioce"` matches `"invoice_2026.pdf"`).

Ranking is calculated by combining CD-rank relevance scores with trigram filename similarities. Matches inside document content return text excerpts with query keywords enclosed in `<mark>` tags.

---

## 9. Queue & Background Worker

* Run via `python -m app.worker` under the queue name `idp`.
* Windows processes run `rq.SimpleWorker` (no-fork mode); Linux environments utilize standard `rq.Worker(with_scheduler=True)`.
* Failed jobs are scheduled to retry up to 3 times (`interval=[10, 30, 60]` seconds).
* **Storage Cleanup Jobs**: Permanent file deletions are offloaded to background worker queues (`delete_storage_files`) to keep API response times minimal.

---

## 10. Frontend Application Structure

The Next.js frontend uses Next.js App Router layout routing:
* `(app)/dashboard` — KPI gauges, recent actions, and storage counters.
* `(app)/documents` — Paginated workspace list (polls every 3 seconds for active ingestion).
* `(app)/documents/[id]` — Split view containing: iframe file viewer, extracted keys tab, metadata properties log, and interactive JSON explorer. Renders split badging indicators.
* `(app)/spreadsheet` — Spreadsheet Center page: cascading filters, checkboxes columns picker, table preview, and CSV downloader.
* `(app)/search` — Match results with yellow highlighted excerpts.
* `(app)/settings` — Organization profile, API key generation, and tags management.

---

## 11. Configuration Reference

Key variables inside `backend/.env` and `frontend/.env.local`:

| Variable | Type | Default / Scope | Purpose |
|---|---|---|---|
| `DATABASE_URL` | string | required | Direct transaction connection to Supabase Postgres pooler (port 6543) |
| `ALEMBIC_DATABASE_URL` | string | required | Alembic session connection (port 5432) |
| `SUPABASE_SERVICE_ROLE_KEY` | string | required | Admin privileges token bypassing RLS |
| `REDIS_URL` | string | required | Redis server link |
| `VLM_BASE_URL` | string | required | OpenAI-compatible endpoint for Qwen-VL model |
| `CONFIDENCE_THRESHOLD` | float | `0.7` | Minimum score to mark extractions as `"accepted"` |
| `MAX_UPLOAD_MB` | int | `50` | Ingestion payload limit size |
| `NEXT_PUBLIC_API_BASE_URL` | string | `http://localhost:8001/api` | Target API base URL for frontend requests |

---

## 12. Testing Framework & Test Suite

Run tests via:
```bash
pytest app/tests -v
```
The test suite consists of **243** active tests:
* `test_contract_camelcase.py`: Validates camelCase JSON properties format.
* `test_tenant_isolation.py` & `test_search_tenant_isolation.py`: Verifies database RLS policies.
* `test_ai_extraction.py`: Mocks VLM prompts, JSON repair algorithms, and text chunking loops.
* `test_export_spreadsheet.py`: Mock database unit tests verifying metadata selectors, preview modes, and CSV export.

---

## 13. Project Directory Layout

```
digital_ui/
├── backend/
│   ├── app/
│   │   ├── core/                  # DB connection, security logic, storage adapter
│   │   ├── models/                # All 16 database tables
│   │   ├── modules/
│   │   │   ├── auth/              # Bootstrap flows
│   │   │   ├── files/             # Library CRUD
│   │   │   ├── search/            # CD-rank and trigram queries
│   │   │   ├── idp/               # Background queue tasks, OCR & VLM pipelines
│   │   │   └── export/            # Spreadsheet export module
│   │   ├── migrations/            # Database Alembic version files
│   │   └── tests/                 # Full pytest suite
│   ├── worker.py                  # RQ worker entrypoint
│   └── pyproject.toml             # Python package dependencies
│
└── frontend/
    ├── app/                       # Page routing layouts
    ├── components/                # UI sidebar & status badges
    ├── lib/                       # API clients & session context providers
    └── types/                     # TypeScript definitions
```

---

# Part 2 — System Operations Guide

---

## 14. What is DataWiz?

DataWiz is an intelligent cloud archive for small businesses. It automatically reads uploaded paperwork (invoices, receipts, contracts, reports), extracts critical billing information, organizes records using automated matching tags, and allows users to search documents by their content or file names.

---

## 15. How Data Flows - Step by Step

1. **User Sign-In**: User logs in. First-time registration initializes their isolated tenant workspace.
2. **File Ingestion**: User drags files into the Upload zone. Bytes are written toSupabase Storage, and processing tasks are enqueued.
3. **Text Acquisition**: Background workers open the document. If it is a digital PDF, text is copied. If it is a scanned image, OCR engines read the text.
4. **Structured Parsing**: The system checks if the document layout matches a saved template. If it does, coordinates extract fields immediately. If not, the AI parses the document dynamically.
5. **Auto-Match Routing**: The rules engine compares text strings against target patterns, linking matching tags and correspondents.
6. **Analytics & CSV Export**: Users select documents, configure custom column criteria in the Spreadsheet Center, and download accounting-ready spreadsheets.

---

## 16. Current Implemented Features

* **Multi-Tenant RLS Boundaries**: Complete database security shielding records across tenants.
* **Dual Ingestion Modi**: Automatic path detection (Digital PDF read vs. OCR scan).
* **Deterministic Layout Matching**: Matches templates to avoid AI costs.
* **Soft Delete Trash Bin**: 30-day recycle trash management with S3 cleaner jobs.
* **Rules Engine Classifier**: Automates correspondent assignment and tag linking.
* **Editable Custom Fields**: Add custom metadata structures and edit incorrect values.
* **Accounting Spreadsheet center**: Granular line-item/summary export sheets.
* **Fuzzy Typo-Tolerant Search**: Searches content and filename text with keyword highlights.

---

## 17. Planned Roadmap & Future Features

### Short-Term
* **Spreadsheet Usability Improvements**: Table cell overflow styling, grid spacing refinements, and filter reset options.
* **Auto-Classification**: Keyword and layout analysis to automatically assign document types (e.g. *invoice*, *receipt*, *contract*) on initial file ingestion.

### Medium-Term
* **Contextual RAG Chatbot**: Enabling multi-tenant vector searches via `pgvector` and local `SentenceTransformer` embeddings (`all-MiniLM-L6-v2`) to query document content conversationally.
