# System Architecture & Database Schema Specification

This document provides an exact technical specification of the DataWiz Intelligent Document Processing (IDP) and Digital Archiving System architecture, pipeline workflows, template matching mechanics, hybrid search engine, and full PostgreSQL database schema synchronized directly with the `backend/app/models/` Python codebase.

---

## 🏛️ 1. High-Level System Architecture

The system is designed as a modular microservice architecture separating web UI, API routing, asynchronous background processing, database storage, and GPU AI inference.

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

### Document Processing States (`backend/app/models/document.py`)
During ingestion, a document transitions through the following exact status states:
- **`queued`**: File uploaded, enqueued to Redis background worker.
- **`extracting_text`**: Worker is extracting plain text or reading text layers.
- **`ocr_processing`**: Worker is running PaddleOCR on scanned images/pages.
- **`ai_extraction`**: Worker is invoking Qwen3-VL-4B visual-language processing.
- **`completed`**: Pipeline finished successfully and confidence requirements were met.
- **`needs_review`**: Pipeline completed but extraction confidence was below threshold.
- **`failed`**: Pipeline encountered an error and ran out of retries.

---

## 🔍 3. Search Engine & RAG Subsystem Architecture

The search service (`app.modules.search.service`) executes a **Hybrid Search Engine** combining three distinct search techniques:

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

---

## 🗄️ 4. Synchronized Database Schema Specification

Below is the code-synchronized specification of every model in `backend/app/models/`.

### 1. `tenants` (`app.models.tenant.Tenant`)
- `id` (UUID, Primary Key, Default `gen_random_uuid()`)
- `name` (String, Not Null)
- `slug` (String, Unique, Not Null)
- `trash_retention_days` (Integer, Default `30`)
- `created_at`, `updated_at` (DateTime with Timezone)

### 2. `users` (`app.models.user.User`)
- `id` (UUID, Primary Key, References `auth.users(id)`)
- `tenant_id` (UUID, Foreign Key -> `tenants.id`)
- `email` (String, Not Null)
- `full_name` (String, Nullable)
- `role` (String, Default `'member'`) — (`'owner'`, `'admin'`, `'member'`, `'viewer'`)
- `created_at` (DateTime with Timezone)

### 3. `documents` (`app.models.document.Document`)
- `id` (UUID, Primary Key)
- `tenant_id` (UUID, Foreign Key -> `tenants.id`, Not Null, Indexed)
- `filename` (String, Not Null)
- `original_filename` (String, Not Null)
- `mime_type` (String, Not Null)
- `size_bytes` (BigInteger, Not Null)
- `storage_key` (String, Not Null)
- `status` (String, Not Null, Default `'queued'`)
- `error_message` (Text, Nullable)
- `document_type_id` (UUID, Foreign Key -> `document_types.id`, Nullable)
- `template_id` (UUID, Foreign Key -> `document_templates.id`, Nullable)
- `document_type` (String, Default `'other'`)
- `page_count` (Integer, Nullable)
- `has_text_layer` (Boolean, Default `false`)
- `ocr_used` (Boolean, Default `false`)
- `ocr_confidence` (REAL, Nullable)
- `extracted_data` (JSONB, Nullable)
- `extracted_text` (Text, Nullable)
- `confidence` (REAL, Nullable)
- `search_tsv` (TSVECTOR, Nullable) — Full-text search GIN index
- `checksum` (String(64), Nullable) — SHA-256 hash for deduplication
- `title` (String, Nullable)
- `document_date` (Date, Nullable)
- `thumbnail_key` (String, Nullable)
- `correspondent_id` (UUID, Foreign Key -> `correspondents.id`, Nullable)
- `vendor` (String, Nullable)
- `invoice_no` (String, Nullable)
- `total_amount` (Numeric(12, 2), Nullable)
- `currency` (String(8), Nullable)
- `duplicate_of_document_id` (UUID, Foreign Key -> `documents.id`, Nullable)
- `deleted_at` (DateTime with Timezone, Nullable) — Soft delete
- `uploaded_by` (UUID, Foreign Key -> `users.id`, Not Null)
- `uploaded_at` (DateTime with Timezone, Default `now()`)
- `processed_at` (DateTime with Timezone, Nullable)

### 4. `document_types` (`app.models.document_type.DocumentType`)
- `id` (UUID, Primary Key)
- `tenant_id` (UUID, Nullable, Foreign Key -> `tenants.id`) — `NULL` denotes global system types.
- `name` (String, Not Null) — e.g. `'invoice'`, `'receipt'`
- `description` (Text, Nullable)
- `json_schema` (JSONB, Nullable) — Soft schema for extraction confidence scoring
- `is_system` (Boolean, Default `false`) — `true` for system-seeded types
- `extraction_method` (String, Default `'paddle_qwen'`) — (`'paddle_qwen'`, `'cascade'`)

### 5. `document_templates` (`app.models.document_template.DocumentTemplate`)
- `id` (UUID, Primary Key)
- `tenant_id` (UUID, Foreign Key -> `tenants.id`, Not Null)
- `document_type_id` (UUID, Foreign Key -> `document_types.id`, Not Null)
- `name` (String, Not Null)
- `fingerprint` (String, Not Null) — Identifies layout visual structure
- `field_mappings` (JSONB, Not Null, Default `{}`)
- `status` (String, Default `'candidate'`) — (`'candidate'`, `'promoted'`, `'disabled'`)
- `examples_count` (Integer, Default `0`)
- `confidence` (REAL, Nullable)
- `version` (Integer, Default `1`)
- `extraction_method` (String, Default `'default'`)
- `is_default` (Boolean, Default `false`)
- `use_image` (Boolean, Default `false`)
- `use_ocr` (Boolean, Default `true`)
- `sample_document_id` (UUID, Foreign Key -> `documents.id`, Nullable)

### 6. `extractions` (`app.models.extraction.Extraction`)
- `id` (UUID, Primary Key)
- `tenant_id` (UUID, Foreign Key -> `tenants.id`, Not Null)
- `document_id` (UUID, Foreign Key -> `documents.id`, Not Null)
- `template_id` (UUID, Foreign Key -> `document_templates.id`, Nullable)
- `raw_payload` (JSONB, Nullable)
- `normalized_payload` (JSONB, Nullable)
- `field_confidences` (JSONB, Nullable)
- `overall_confidence` (REAL, Nullable)
- `accepted_by_user` (Boolean, Default `false`)

### 7. `processing_jobs` (`app.models.processing_job.ProcessingJob`)
- `id` (UUID, Primary Key)
- `tenant_id` (UUID, Foreign Key -> `tenants.id`, Not Null)
- `document_id` (UUID, Foreign Key -> `documents.id`, Not Null)
- `job_type` (String, Not Null)
- `status` (String, Default `'pending'`) — (`'pending'`, `'processing'`, `'completed'`, `'failed'`)
- `error_message` (Text, Nullable)
- `started_at`, `completed_at` (DateTime with Timezone)

### 8–18. Additional Registered Entities
- **`tags`** & **`document_tags`**: Tag definitions and many-to-many junction mapping.
- **`correspondents`**: Vendor/sender entities (`name`, `email`, `match_rules`).
- **`custom_fields`** & **`document_field_values`**: Dynamic tenant-specific custom fields and typed document field values.
- **`saved_views`**: Preset search and spreadsheet view filters.
- **`document_shares`**: Secure temporary document share tokens.
- **`ai_usage`**: LLM & VLM token telemetry logs.
- **`activity_events`**: Audit trail of document modifications.
- **`api_keys`**: Hashed developer API access tokens.

---

## 🔒 5. Row Level Security (RLS) Policy Pattern

Every database transaction executes `SET LOCAL app.current_tenant = '{tenant_id}'`, ensuring native PostgreSQL RLS enforcement:

```sql
-- Example Document Isolation Policy
CREATE POLICY tenant_isolation_documents ON documents
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant', true)::uuid);

-- Example Global + Tenant Hybrid Policy
CREATE POLICY tenant_isolation_document_types ON document_types
    FOR SELECT
    USING (tenant_id IS NULL OR tenant_id = current_setting('app.current_tenant', true)::uuid);
```
