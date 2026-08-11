# System Architecture & Database Schema Specification

This document provides a technical specification of the DataWiz Intelligent Document Processing (IDP) and Digital Archiving System architecture, pipeline workflows, template matching mechanics, hybrid search engine, and full PostgreSQL database schema.

---

## 🏛️ 1. High-Level System Architecture

The system is designed as a modular, decoupled microservice architecture separating web UI, API routing, asynchronous background processing, database storage, and GPU AI inference.

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       USER / BROWSER INTERFACE                                   │
│                                                                                                  │
│   ┌─────────────────────┐    ┌─────────────────────┐    ┌────────────────────────────────────┐   │
│   │  Document Dashboard │    │  IDP Control Center │    │        Spreadsheet Grid View       │   │
│   │  (Inbox & Uploads)  │    │  (Templates/Schemas)│    │       (Bulk Metadata Editing)      │   │
│   └──────────┬──────────┘    └──────────┬──────────┘    └─────────────────┬──────────────────┘   │
└──────────────┼──────────────────────────┼─────────────────────────────────┼──────────────────────┘
               │                          │                                 │
               └──────────────────────────┼─────────────────────────────────┘
                                          │ HTTP REST Requests (JWT Auth Header)
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                     FASTAPI BACKEND API GATEWAY                                  │
│                                                                                                  │
│  - Middleware: CORS, Security Headers, JWT Validation, Tenant Context Setup (app.current_tenant) │
│  - Routers: /files, /idp, /templates, /types, /search, /spreadsheet, /auth                      │
└──────────────┬────────────────────────────────────────────────────────────┬──────────────────────┘
               │                                                            │
               │ Enqueue Processing Job                                     │ Query & Persist Records
               ▼                                                            ▼
┌─────────────────────────────┐                             ┌──────────────────────────────────────┐
│     Redis Task Queue (RQ)   │                             │      Supabase PostgreSQL Database    │
│   Queue Name: 'idp' (:6379) │                             │   - Row Level Security (RLS)         │
└──────────────┬──────────────┘                             │   - JSONB Document Extractions       │
               │ Dequeue Job                                │   - Full-Text & Trigram Indexes      │
               ▼                                            └───────────────────▲──────────────────┘
┌─────────────────────────────┐                                                 │
│    Async IDP Worker Job     │                                                 │
│   (backend/app/worker.py)   │                                                 │
│                             │                                                 │
│  1. Download Document File  ├─────────────────────────────────────────────────┤ (Fetch Storage Key)
│  2. Run Strategy Selection  │                                                 │
│  3. Call Remote AI Server   ├──────────────────────────────┐                  │
│  4. Extract Schema Fields   │                              │                  │
│  5. Score Confidence        │                              │                  │
│  6. Store Extractions & DB  ├──────────────────────────────┼──────────────────┘
└─────────────────────────────┘                              │
                                                             │ HTTP Post Payload (Base64/Image)
                                                             ▼
                                            ┌──────────────────────────────────┐
                                            │    Remote AI GPU Inference Server│
                                            │    - PaddleOCR Engine (OCR)      │
                                            │    - Qwen3-VL-4B-Instruct (VLM)  │
                                            └──────────────────────────────────┘
```

---

## 🔄 2. IDP Ingestion & Processing Pipeline

### Step 1: Document Upload & Storage Ingestion
1. User uploads a file (PDF, PNG, JPEG) via the Frontend Upload interface.
2. `POST /api/documents/upload` receives the file stream, calculates an MD5 checksum for deduplication, and streams the file payload directly to Supabase Storage bucket `documents` under key `{tenant_id}/{document_id}/{filename}`.
3. A record is inserted into `documents` with status `'uploaded'`.
4. A processing job is enqueued to Redis (`IDP_QUEUE_NAME`).

### Step 2: Strategy Selection & Template Matching
When the worker picks up the job (`app.modules.files.service.process_document`):
1. **Template Fingerprint Inspection**: The document structure, filename, and visual headers are compared against active `document_templates` for the tenant.
2. **Strategy Dispatch**:
   - **`paddle_qwen` (Hybrid Default)**: Runs PaddleOCR to extract text boundaries and line bounding boxes, followed by Qwen3-VL-4B to parse visual structure and extract key-value JSON fields.
   - **`vlm_only`**: Direct visual-language model pass over document images.
   - **`ocr_only`**: Fast text extraction for standard digital PDFs with existing text layers.

### Step 3: Structured Key-Value Field Extraction
1. Target field definitions (names, types, descriptions, validation regex) are fetched from `document_type_fields` and `document_templates`.
2. The AI prompt injector merges the target JSON schema with customized prompt hints configured in the IDP Control Center.
3. The response is validated against Pydantic schema schemas.

### Step 4: Confidence Scoring & Auto-Promotion
1. Field-level confidence scores are calculated based on OCR text alignment and model log-probabilities.
2. Overall document confidence is derived:
   - If `confidence >= CONFIDENCE_THRESHOLD` (default `0.7`), the document status transitions to `'processed'`.
   - If confidence is below threshold, status becomes `'review_required'` for human validation in the Inbox.

---

## 🔍 3. Search Engine & RAG Subsystem Architecture

The search service (`app.modules.search.service`) executes a **Hybrid Search Engine** combining three distinct search techniques over ingested documents:

```
                          User Search Query String (e.g. "Acme Invoice 2026")
                                                  │
                ┌─────────────────────────────────┼─────────────────────────────────┐
                │                                 │                                 │
                ▼                                 ▼                                 ▼
   1. Full-Text Keyword Search          2. Fuzzy Trigram Match           3. Vector Semantic Search
   (documents.search_tsv @@             (word_similarity over            (pgvector Cosine Distance
   websearch_to_tsquery)                title & original_filename)       over 1536d embeddings)
                │                                 │                                 │
                └─────────────────────────────────┼─────────────────────────────────┘
                                                  │
                                                  ▼
                                 Reciprocal Rank Fusion (RRF) & Re-Ranking
                                                  │
                                                  ▼
                                    Sorted Document Results Payload
```

1. **Full-Text Keyword Search (FTS)**:
   PostgreSQL `search_tsv` (`tsvector`) column automatically updated via DB triggers, matching queries using `websearch_to_tsquery('english', q)` and `to_tsquery('english', q + ':*')`.
2. **Trigram Fuzzy Matching (`pg_trgm`)**:
   Uses `word_similarity(q, title)` and `word_similarity(q, original_filename)` to catch typos and partial filename matches.
3. **Vector Semantic Search (`pgvector`)**:
   Calculates cosine similarity distance between query embeddings and document chunk vector embeddings.

---

## 🗄️ 4. Complete PostgreSQL Database Schema

The database consists of **18 relational tables** configured with native Supabase Row Level Security (RLS).

### Entity Relationship Map

```
  ┌──────────────┐          1:N         ┌──────────────┐
  │   tenants    │─────────────────────>│    users     │
  └──────┬───────┘                      └──────────────┘
         │
         │ 1:N
         ├─────────────────────────────>┌──────────────────────┐
         │                              │    document_types    │
         │                              └──────────┬───────────┘
         │                                         │ 1:N
         │                                         ▼
         │                              ┌──────────────────────┐ 1:N ┌──────────────────────┐
         ├─────────────────────────────>│  document_templates  │────>│ document_type_fields │
         │                              └──────────┬───────────┘     └──────────────────────┘
         │                                         │ 1:N
         │ 1:N                                     ▼
         ├─────────────────────────────>┌──────────────────────┐
         │                              │      documents       │
         │                              └──────────┬───────────┘
         │                                         │
         │                                         ├───────────────> 1:N  ┌──────────────────────┐
         │                                         │                      │     extractions      │
         │                                         │                      └──────────────────────┘
         │                                         ├───────────────> 1:N  ┌──────────────────────┐
         │                                         │                      │    processing_jobs   │
         │                                         │                      └──────────────────────┘
         │                                         ├───────────────> M:N  ┌──────────────────────┐
         │                                         │                      │         tags         │
         │                                         │                      └──────────────────────┘
         │                                         └───────────────> 1:N  ┌──────────────────────┐
         │                                                                │  correspondents /    │
         │                                                                │  custom_fields /     │
         │                                                                │  saved_views / etc.  │
         └───────────────────────────────────────────────────────────────>└──────────────────────┘
```

---

### Master Table Schema Specifications

#### 1. `tenants`
Defines isolated customer tenant accounts.
- `id` (UUID, Primary Key, Default `gen_random_uuid()`)
- `name` (VARCHAR(255), Not Null)
- `slug` (VARCHAR(255), Unique, Not Null)
- `trash_retention_days` (INTEGER, Default `30`)
- `created_at` (TIMESTAMPTZ, Default `now()`)
- `updated_at` (TIMESTAMPTZ, Default `now()`)

#### 2. `users`
App user accounts mapped to Supabase Auth UUIDs.
- `id` (UUID, Primary Key, References `auth.users(id)`)
- `tenant_id` (UUID, Not Null, Foreign Key -> `tenants.id`)
- `email` (VARCHAR(255), Not Null)
- `full_name` (VARCHAR(255))
- `role` (VARCHAR(50), Default `'member'`) — (`'owner'`, `'admin'`, `'member'`, `'viewer'`)
- `created_at` (TIMESTAMPTZ, Default `now()`)

#### 3. `documents`
Master record for uploaded physical and digital files.
- `id` (UUID, Primary Key, Default `gen_random_uuid()`)
- `tenant_id` (UUID, Not Null, Foreign Key -> `tenants.id`)
- `filename` (VARCHAR(255), Not Null)
- `original_filename` (VARCHAR(255), Not Null)
- `mime_type` (VARCHAR(100), Not Null)
- `size_bytes` (BIGINT, Not Null)
- `storage_key` (TEXT, Not Null)
- `thumbnail_key` (TEXT)
- `status` (VARCHAR(50), Not Null, Default `'uploaded'`) — (`'uploaded'`, `'processing'`, `'processed'`, `'review_required'`, `'failed'`, `'archived'`)
- `error_message` (TEXT)
- `document_type_id` (UUID, Foreign Key -> `document_types.id`)
- `template_id` (UUID, Foreign Key -> `document_templates.id`)
- `page_count` (INTEGER, Default `1`)
- `has_text_layer` (BOOLEAN, Default `false`)
- `ocr_used` (BOOLEAN, Default `false`)
- `ocr_confidence` (DOUBLE PRECISION)
- `extracted_data` (JSONB, Default `'{}'`)
- `extracted_text` (TEXT)
- `confidence` (DOUBLE PRECISION)
- `search_tsv` (TSVECTOR) — Full-text search index vector
- `checksum` (VARCHAR(64)) — MD5 file hash
- `title` (VARCHAR(255))
- `document_date` (DATE)
- `vendor` (VARCHAR(255))
- `invoice_no` (VARCHAR(100))
- `total_amount` (NUMERIC(15, 2))
- `currency` (VARCHAR(10))
- `correspondent_id` (UUID, Foreign Key -> `correspondents.id`)
- `duplicate_of_document_id` (UUID, Foreign Key -> `documents.id`)
- `uploaded_by` (UUID, Foreign Key -> `users.id`)
- `uploaded_at` (TIMESTAMPTZ, Default `now()`)
- `processed_at` (TIMESTAMPTZ)
- `deleted_at` (TIMESTAMPTZ) — Soft delete timestamp

#### 4. `document_types`
System and custom document classifications (*Invoice*, *Receipt*, etc.).
- `id` (UUID, Primary Key, Default `gen_random_uuid()`)
- `tenant_id` (UUID, Nullable, Foreign Key -> `tenants.id`) — `NULL` denotes global system types.
- `name` (VARCHAR(100), Not Null)
- `slug` (VARCHAR(100), Not Null)
- `description` (TEXT)
- `icon` (VARCHAR(50))
- `is_system` (BOOLEAN, Default `false`)
- `created_at` (TIMESTAMPTZ, Default `now()`)

#### 5. `document_templates`
IDP extraction schemas and configuration presets.
- `id` (UUID, Primary Key, Default `gen_random_uuid()`)
- `tenant_id` (UUID, Foreign Key -> `tenants.id`)
- `document_type_id` (UUID, Not Null, Foreign Key -> `document_types.id`)
- `name` (VARCHAR(255), Not Null)
- `description` (TEXT)
- `extraction_strategy` (VARCHAR(50), Default `'paddle_qwen'`)
- `target_schema` (JSONB, Not Null, Default `'{}'`) — JSON Schema field definitions
- `prompt_hints` (TEXT) — Custom prompt guidelines for VLM parsing
- `sample_file_key` (TEXT)
- `is_active` (BOOLEAN, Default `true`)
- `created_at` (TIMESTAMPTZ, Default `now()`)

#### 6. `document_type_fields`
Field definition rules per document type.
- `id` (UUID, Primary Key, Default `gen_random_uuid()`)
- `tenant_id` (UUID, Foreign Key -> `tenants.id`)
- `document_type_id` (UUID, Foreign Key -> `document_types.id`)
- `field_name` (VARCHAR(100), Not Null)
- `field_label` (VARCHAR(100), Not Null)
- `data_type` (VARCHAR(50), Not Null) — (`'string'`, `'number'`, `'date'`, `'boolean'`, `'array'`)
- `is_required` (BOOLEAN, Default `false`)
- `description` (TEXT)

#### 7. `extractions`
Detailed field extraction history and confidence breakdown per document run.
- `id` (UUID, Primary Key, Default `gen_random_uuid()`)
- `tenant_id` (UUID, Foreign Key -> `tenants.id`)
- `document_id` (UUID, Foreign Key -> `documents.id`)
- `template_id` (UUID, Foreign Key -> `document_templates.id`)
- `extraction_method` (VARCHAR(50))
- `raw_response` (JSONB)
- `structured_data` (JSONB)
- `field_confidences` (JSONB)
- `overall_confidence` (DOUBLE PRECISION)
- `created_at` (TIMESTAMPTZ, Default `now()`)

#### 8. `processing_jobs`
Background job tracking for Redis RQ tasks.
- `id` (UUID, Primary Key, Default `gen_random_uuid()`)
- `tenant_id` (UUID, Foreign Key -> `tenants.id`)
- `document_id` (UUID, Foreign Key -> `documents.id`)
- `job_type` (VARCHAR(50), Not Null)
- `status` (VARCHAR(50), Not Null, Default `'pending'`)
- `retry_count` (INTEGER, Default `0`)
- `error_log` (TEXT)
- `created_at` (TIMESTAMPTZ, Default `now()`)
- `completed_at` (TIMESTAMPTZ)

#### 9–18. Supporting Tables
- **`tags`**: Document taxonomy tags (`id`, `tenant_id`, `name`, `color`).
- **`correspondents`**: Senders/Vendors/Organizations (`id`, `tenant_id`, `name`, `email`, `match_rules`).
- **`custom_fields`**: Tenant-defined metadata fields (`id`, `tenant_id`, `name`, `field_type`).
- **`saved_views`**: User custom search filters and grid view settings (`id`, `user_id`, `name`, `query_params`).
- **`document_shares`**: External document sharing links with expiration (`id`, `document_id`, `share_token`, `expires_at`).
- **`ai_usage`**: Token consumption telemetry (`id`, `tenant_id`, `prompt_tokens`, `completion_tokens`, `model_name`).
- **`activity_events`**: Audit log of document changes (`id`, `tenant_id`, `user_id`, `event_type`, `payload`).
- **`api_keys`**: Developer API authentication tokens (`id`, `tenant_id`, `key_hash`, `name`, `permissions`).

---

## 🔒 5. Multi-Tenancy Security & Row Level Security (RLS)

All database operations enforce multi-tenant isolation via **PostgreSQL Row Level Security (RLS)**.

### RLS Execution Mechanism
1. Every API request authenticates the user's Supabase JWT token.
2. The FastAPI DB session middleware inspects `jwt.claims.tenant_id` and executes:
   ```sql
   SET LOCAL app.current_tenant = 'tenant-uuid-here';
   ```
3. Database tables enforce native RLS policies evaluating `tenant_id`:
   ```sql
   -- Standard Tenant Isolation Policy Pattern
   CREATE POLICY tenant_isolation_documents ON documents
       FOR ALL
       USING (tenant_id = current_setting('app.current_tenant', true)::uuid);
   ```
4. Global system records (e.g. system document types) use hybrid policies:
   ```sql
   CREATE POLICY tenant_isolation_document_types ON document_types
       FOR SELECT
       USING (tenant_id IS NULL OR tenant_id = current_setting('app.current_tenant', true)::uuid);
   ```

---

## ⚡ 6. Database Indexes & Performance Optimization

- **Full-Text Search Index**:
  ```sql
  CREATE INDEX idx_documents_search_tsv ON documents USING gin(search_tsv);
  ```
- **Trigram Fuzzy Search Indexes**:
  ```sql
  CREATE INDEX idx_documents_title_trgm ON documents USING gin(lower(title) gin_trgm_ops);
  CREATE INDEX idx_documents_filename_trgm ON documents USING gin(lower(original_filename) gin_trgm_ops);
  ```
- **JSONB Ingestion Index**:
  ```sql
  CREATE INDEX idx_documents_extracted_data ON documents USING gin(extracted_data jsonb_path_ops);
  ```
- **Soft Delete Partial Index**:
  ```sql
  CREATE INDEX idx_documents_active ON documents (tenant_id, uploaded_at DESC) WHERE deleted_at IS NULL;
  ```
