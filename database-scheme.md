# DataWiz Database Schema Reference

This document provides a detailed specification of all 16 PostgreSQL tables, relationships, constraints, indexes, and Row Level Security (RLS) policies enforcing multi-tenant isolation.

---

## Entity Relationship Overview

```
                          ┌──────────────┐
                          │   tenants    │
                          └──────┬───────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
         ▼                       ▼                       ▼
  ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
  │    users    │         │  documents  │         │    tags     │
  └─────────────┘         └──────┬──────┘         └──────┬──────┘
                                 │                       │
                                 ▼                       ▼
                          ┌─────────────┐         ┌─────────────┐
                          │extractions/ │         │document_tags│
                          │field_values │         └─────────────┘
                          └─────────────┘
```

---

## Table Definitions

### 1. `tenants`
Root tenant configuration and storage meter.
- `id` (UUID, PK)
- `name` (VARCHAR, NOT NULL)
- `plan` (VARCHAR, NOT NULL, DEFAULT `'starter'`)
- `storage_used_bytes` (BIGINT, NOT NULL, DEFAULT 0)
- `storage_limit_bytes` (BIGINT, NOT NULL, DEFAULT 10737418240)
- `llm_monthly_token_cap` (INTEGER, NULLABLE)
- `created_at` (TIMESTAMPTZ, DEFAULT `now()`)

### 2. `users`
System users bound to Supabase Auth UUIDs.
- `id` (UUID, PK, matches Supabase `sub`)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `email` (VARCHAR, UNIQUE, NOT NULL)
- `name` (VARCHAR, NOT NULL)
- `role` (VARCHAR, NOT NULL, DEFAULT `'user'`)
- `avatar_initials` (VARCHAR, NOT NULL)
- `created_at` (TIMESTAMPTZ)
- `last_login_at` (TIMESTAMPTZ, NULLABLE)

### 3. `documents`
Central archive file records.
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `filename` (VARCHAR, NOT NULL)
- `original_filename` (VARCHAR, NOT NULL)
- `mime_type` (VARCHAR, NOT NULL)
- `size_bytes` (BIGINT, NOT NULL)
- `storage_key` (VARCHAR, NOT NULL)
- `status` (VARCHAR, NOT NULL, DEFAULT `'queued'`)
- `error_message` (TEXT, NULLABLE)
- `document_type` (VARCHAR, NOT NULL, DEFAULT `'other'`)
- `document_type_id` (UUID, FK -> `document_types.id` SET NULL)
- `template_id` (UUID, FK -> `document_templates.id` SET NULL)
- `page_count` (INTEGER, NULLABLE)
- `has_text_layer` (BOOLEAN, NOT NULL, DEFAULT false)
- `ocr_used` (BOOLEAN, NOT NULL, DEFAULT false)
- `ocr_engine` (VARCHAR, NULLABLE)
- `ocr_confidence` (REAL, NULLABLE)
- `vlm_model` (VARCHAR, NULLABLE)
- `extraction_method` (VARCHAR, NULLABLE)
- `extracted_data` (JSONB, NULLABLE)
- `extracted_text` (TEXT, NULLABLE)
- `confidence` (REAL, NULLABLE)
- `search_tsv` (TSVECTOR, NULLABLE)
- `checksum` (VARCHAR(64), NULLABLE)
- `title` (VARCHAR, NULLABLE)
- `document_date` (DATE, NULLABLE)
- `has_thumbnail` (BOOLEAN, NOT NULL, DEFAULT false)
- `thumbnail_key` (VARCHAR, NULLABLE)
- `correspondent_id` (UUID, FK -> `correspondents.id` SET NULL)
- `deleted_at` (TIMESTAMPTZ, NULLABLE)
- `uploaded_by` (UUID, FK -> `users.id` RESTRICT)
- `uploaded_at` (TIMESTAMPTZ, NOT NULL, DEFAULT `now()`)
- `processed_at` (TIMESTAMPTZ, NULLABLE)

### 4. `document_types`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE, NULLABLE)
- `name` (VARCHAR, NOT NULL)
- `description` (TEXT, NULLABLE)
- `json_schema` (JSONB, NULLABLE)
- `is_system` (BOOLEAN, NOT NULL, DEFAULT false)
- `extraction_method` (VARCHAR, NOT NULL, DEFAULT `'default'`)
- `created_at` (TIMESTAMPTZ)

### 5. `document_templates`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `document_type_id` (UUID, FK -> `document_types.id` CASCADE)
- `name` (VARCHAR, NOT NULL)
- `fingerprint` (VARCHAR, NOT NULL)
- `field_mappings` (JSONB, NOT NULL, DEFAULT `'{}'`)
- `status` (VARCHAR, NOT NULL, DEFAULT `'candidate'`)
- `examples_count` (INTEGER, NOT NULL, DEFAULT 0)
- `confidence` (REAL, NULLABLE)
- `version` (INTEGER, NOT NULL, DEFAULT 1)
- `extraction_method` (VARCHAR, NOT NULL, DEFAULT `'default'`)
- `is_default` (BOOLEAN, NOT NULL, DEFAULT false)
- `use_image` (BOOLEAN, NOT NULL, DEFAULT false)
- `use_ocr` (BOOLEAN, NOT NULL, DEFAULT true)
- `sample_document_id` (UUID, FK -> `documents.id` SET NULL)
- `created_at` (TIMESTAMPTZ, DEFAULT `now()`)
- `updated_at` (TIMESTAMPTZ, DEFAULT `now()`)

### 6. `extractions`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `document_id` (UUID, FK -> `documents.id` CASCADE)
- `template_id` (UUID, FK -> `document_templates.id` SET NULL)
- `method` (VARCHAR, NOT NULL)
- `model_name` (VARCHAR, NULLABLE)
- `output` (JSONB, NULLABLE)
- `confidence` (REAL, NULLABLE)
- `status` (VARCHAR, NOT NULL)
- `created_at` (TIMESTAMPTZ)

### 7. `processing_jobs`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `document_id` (UUID, FK -> `documents.id` CASCADE)
- `status` (VARCHAR, NOT NULL)
- `stage` (VARCHAR, NULLABLE)
- `attempts` (INTEGER, NOT NULL, DEFAULT 0)
- `error` (TEXT, NULLABLE)
- `enqueued_at` (TIMESTAMPTZ, DEFAULT `now()`)
- `started_at` (TIMESTAMPTZ, NULLABLE)
- `finished_at` (TIMESTAMPTZ, NULLABLE)
- `duration_ms` (INTEGER, NULLABLE)

### 8. `activity_events`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `type` (VARCHAR, NOT NULL)
- `document_id` (UUID, FK -> `documents.id` SET NULL)
- `document_name` (VARCHAR, NULLABLE)
- `user_id` (UUID, FK -> `users.id` SET NULL)
- `user_name` (VARCHAR, NOT NULL)
- `timestamp` (TIMESTAMPTZ, DEFAULT `now()`)
- `meta` (TEXT, NULLABLE)

### 9. `api_keys`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `name` (VARCHAR, NOT NULL)
- `prefix` (VARCHAR, NOT NULL)
- `hashed_key` (VARCHAR, NOT NULL)
- `created_at` (TIMESTAMPTZ)
- `last_used_at` (TIMESTAMPTZ, NULLABLE)

### 10. `ai_usage`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `document_id` (UUID, FK -> `documents.id` SET NULL)
- `model_name` (VARCHAR, NULLABLE)
- `prompt_tokens` (INTEGER, NOT NULL, DEFAULT 0)
- `completion_tokens` (INTEGER, NOT NULL, DEFAULT 0)
- `total_tokens` (INTEGER, NOT NULL, DEFAULT 0)
- `created_at` (TIMESTAMPTZ, DEFAULT `now()`)

### 11. `tags`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `name` (TEXT, NOT NULL)
- `color` (TEXT, NOT NULL, DEFAULT `'#6B7280'`)
- `match` (TEXT, NOT NULL)
- `matching_algorithm` (TEXT, NOT NULL, DEFAULT `'any'`)
- `is_insensitive` (BOOLEAN, NOT NULL, DEFAULT true)
- `is_inbox_tag` (BOOLEAN, NOT NULL, DEFAULT false)
- `created_at` (TIMESTAMPTZ, DEFAULT `now()`)

### 12. `document_tags`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `document_id` (UUID, FK -> `documents.id` CASCADE)
- `tag_id` (UUID, FK -> `tags.id` CASCADE)

### 13. `correspondents`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `name` (TEXT, NOT NULL)
- `match` (TEXT, NOT NULL)
- `matching_algorithm` (TEXT, NOT NULL, DEFAULT `'any'`)
- `is_insensitive` (BOOLEAN, NOT NULL, DEFAULT true)
- `created_at` (TIMESTAMPTZ, DEFAULT `now()`)

### 14. `custom_fields`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `name` (TEXT, NOT NULL)
- `field_type` (TEXT, NOT NULL)
- `options` (JSONB, NOT NULL, DEFAULT `'[]'`)
- `position` (INTEGER, NOT NULL, DEFAULT 0)
- `created_at` (TIMESTAMPTZ, DEFAULT `now()`)

### 15. `document_field_values`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `document_id` (UUID, FK -> `documents.id` CASCADE)
- `field_id` (UUID, FK -> `custom_fields.id` CASCADE)
- `value` (JSONB, NULLABLE)

### 16. `saved_views`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `name` (TEXT, NOT NULL)
- `filter_state` (JSONB, NOT NULL, DEFAULT `'{}'`)
- `is_default` (BOOLEAN, NOT NULL, DEFAULT false)
- `created_at` (TIMESTAMPTZ, DEFAULT `now()`)

### 17. `document_shares`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `document_id` (UUID, FK -> `documents.id` CASCADE)
- `token` (VARCHAR(64), UNIQUE, NOT NULL)
- `created_by` (UUID, FK -> `users.id` CASCADE)
- `created_at` (TIMESTAMPTZ, DEFAULT `now()`)
- `expires_at` (TIMESTAMPTZ, NULLABLE)

### 18. `document_type_fields`
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id` CASCADE)
- `document_type_id` (UUID, FK -> `document_types.id` CASCADE)
- `field_id` (UUID, FK -> `custom_fields.id` CASCADE)
- `is_required` (BOOLEAN, NOT NULL, DEFAULT false)
- `position` (INTEGER, NOT NULL, DEFAULT 0)
- `created_at` (TIMESTAMPTZ, DEFAULT `now()`)

---

## Row Level Security (RLS) Policy Pattern

Every table enforces isolation via PostgreSQL Row Level Security:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <table> FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_policy ON <table>
  USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
```
