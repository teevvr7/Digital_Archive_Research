# Database Schema — DataWiz Digital Archive

> Complete reference for every table, column, relationship, index, and RLS policy in the system.
> Source of truth: `backend/app/models/*.py` (SQLAlchemy models) + `backend/app/migrations/versions/*.py`
> (Alembic migrations). Current migration head: **`0016`**.

---

## 1. Overview

- **Database:** PostgreSQL, hosted on [Supabase](https://supabase.com).
- **Multi-tenancy model:** pooled (single set of tables shared by every customer), isolated by
  **Row-Level Security (RLS)** — not by separate schemas or databases per tenant.
- **Tenant isolation mechanism:** every tenant-owned table has a non-nullable `tenant_id` column.
  Before any query runs, the application sets a Postgres session variable (a "GUC")
  `app.current_tenant` to the caller's tenant ID. An RLS policy on each table then automatically
  filters every `SELECT`/`INSERT`/`UPDATE`/`DELETE` to rows matching that GUC — the database
  itself enforces the boundary, not application code.
- **Connection role:** the live API/worker connect as a dedicated `app_user` Postgres role that
  does **not** have the `BYPASSRLS` privilege, so RLS is a hard enforcement layer, not just a
  defense-in-depth convenience. Only Alembic (schema migrations) connects as the `postgres`
  superuser, because creating/altering tables requires privileges `app_user` intentionally lacks.
- **18 tables total.** Every table except `tenants` itself has a `tenant_id` foreign key.
  `tenants` is the root of the multi-tenancy model — its own RLS policy filters on `id` instead.
- **IDs:** every primary key is a `UUID`, generated Python-side (`uuid.uuid4()`) at insert time.
- **Timestamps:** stored as `TIMESTAMPTZ` (timezone-aware) so they're unambiguous regardless of
  server or client timezone.

---

## 2. Tables, column by column

### 2.1 `tenants` — the organisation (root of multi-tenancy)

One row per customer organisation. Every other tenant-owned table's `tenant_id` points here.

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | `uuid4()` | Unique tenant identifier |
| `name` | VARCHAR | no | — | Organisation display name, derived from the first user's email domain at signup (e.g. `user@acme.com` → `"Acme"`) |
| `plan` | VARCHAR | no | `"starter"` | Subscription tier (reserved for future `professional`/`enterprise` tiers — not yet billed) |
| `storage_used_bytes` | BIGINT | no | `0` | Running total of bytes stored, incremented on upload, decremented on permanent delete |
| `storage_limit_bytes` | BIGINT | no | `10 GB` | Storage quota; uploads are rejected once this would be exceeded |
| `llm_monthly_token_cap` | INTEGER | yes | `NULL` | Per-tenant override of the monthly VLM token budget. `NULL` = use the global default (`settings.llm_monthly_token_cap_default`, currently 2,000,000) |
| `trash_retention_days` | INTEGER | yes | `NULL` | Per-tenant override of how many days a document stays in the trash before it's permanently auto-deleted. `NULL` = use the global default (`settings.trash_retention_days_default`, currently 30) |
| `trash_last_purged_at` | TIMESTAMPTZ | yes | `NULL` | When the auto-retention purge last ran for this tenant. Used purely to rate-limit the check to roughly once every 24 hours — not user-facing |
| `created_at` | TIMESTAMPTZ | no | `now()` | |

### 2.2 `users` — one row per team member

Mirrors a Supabase Auth user; `id` is literally the same UUID Supabase issues (the `sub` claim in
the JWT), so there is no separate mapping table.

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | Equals Supabase Auth's `auth.users.id` |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | Which organisation this user belongs to |
| `email` | VARCHAR | no | — | **Globally unique** (not per-tenant) — matches Supabase Auth's own global-per-project email uniqueness |
| `name` | VARCHAR | no | — | Display name (derived from email, or set at invite time) |
| `role` | VARCHAR | no | `"user"` | Either `"admin"` or `"user"` — admins can invite/remove teammates, change roles, rename the org |
| `avatar_initials` | VARCHAR | no | `""` | 1–2 uppercase letters shown in the avatar bubble |
| `last_login_at` | TIMESTAMPTZ | yes | `NULL` | `NULL` means an invited teammate has never actually logged in yet (the "pending invite" signal) |
| `created_at` | TIMESTAMPTZ | no | `now()` | |

### 2.3 `documents` — the central archive record (the biggest table)

One row per uploaded file. File **bytes never live in this table** (or in Postgres at all) —
only metadata and the extracted results. The actual bytes live in Supabase Storage, addressed by
`storage_key`.

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `filename` | VARCHAR | no | — | Safe display filename |
| `original_filename` | VARCHAR | no | — | Exactly as the user uploaded it |
| `title` | VARCHAR | yes | `NULL` | User-editable display title; auto-set to `"{vendor} — {invoiceNo}"` when structured extraction succeeds |
| `mime_type` | VARCHAR | no | — | Detected from the file's actual bytes (magic-byte sniffing), never trusted from the filename extension or the browser's claimed content-type |
| `size_bytes` | BIGINT | no | — | |
| `storage_key` | VARCHAR | no | — | Where the bytes live in object storage: `"tenants/{tenant_id}/{sha256}"` — content-addressed, so re-uploading identical bytes is detected as a duplicate |
| `checksum` | VARCHAR(64) | yes | `NULL` | SHA-256 of the file bytes; used for the dedup check above |
| `status` | VARCHAR | no | `"queued"` | Pipeline state — see the status machine below |
| `error_message` | TEXT | yes | `NULL` | Populated only when `status = "failed"`; capped at 2000 characters |
| `document_type` | VARCHAR | no | `"other"` | e.g. `invoice`, `receipt`, `contract` — one of the 7 fixed values (see §2.9) |
| `document_type_id` | UUID (FK → `document_types.id`, SET NULL) | yes | `NULL` | Reserved link to the dynamic type catalog (not yet the primary source of truth — `document_type` above is) |
| `template_id` | UUID (FK → `document_templates.id`, SET NULL) | yes | `NULL` | Reserved for the self-learning template-matching loop |
| `layout_fingerprint` | VARCHAR | yes | `NULL` | Reserved for future layout-based template matching |
| `page_count` | INTEGER | yes | `NULL` | |
| `has_text_layer` | BOOLEAN | no | `false` | True if the PDF had extractable text (no OCR needed) |
| `ocr_used` | BOOLEAN | no | `false` | True if the scanned-image OCR path ran |
| `ocr_confidence` | REAL | yes | `NULL` | Mean per-line OCR confidence (0.0–1.0). `NULL` for non-OCR documents (scored as a clean 1.0 by the quality gate) |
| `extracted_data` | JSONB | yes | `NULL` | The accepted structured-extraction result (vendor, invoice number, amounts, line items, etc.) — an open-ended JSON blob so any document type's fields fit without a schema migration |
| `extracted_text` | TEXT | yes | `NULL` | Full plain-text content, used for full-text search |
| `confidence` | REAL | yes | `NULL` | The accepted extraction's confidence score (0.0–1.0), from whichever tier (deterministic or VLM) produced it |
| `tags` | VARCHAR[] | no | `[]` | **Dead column** — an early array-based tagging approach, superseded by the `tags`/`document_tags` tables (§2.10). Kept only so nothing breaks; never written to |
| `search_tsv` | TSVECTOR | yes | `NULL` | Postgres full-text-search index column, built from title + filename + extracted text |
| `document_date` | DATE | yes | `NULL` | Best-effort guess at "the date on the document" (invoice date, letter date, etc.) — never a hard fact, just a heuristic |
| `thumbnail_key` | VARCHAR | yes | `NULL` | Storage key for a generated preview thumbnail PNG, if one was generated |
| `correspondent_id` | UUID (FK → `correspondents.id`, SET NULL) | yes | `NULL` | The linked vendor/sender, auto-matched or manually assigned |
| `vendor` | VARCHAR | yes | `NULL` | Pulled out of `extracted_data` into its own column so it can be indexed/filtered/exported without reaching into JSON |
| `invoice_no` | VARCHAR | yes | `NULL` | Same idea as `vendor` |
| `total_amount` | NUMERIC(12,2) | yes | `NULL` | Same idea — lets amount-range search work with a normal indexed number column |
| `currency` | VARCHAR(8) | yes | `NULL` | Same idea |
| `duplicate_of_document_id` | UUID (FK → `documents.id`, SET NULL) | yes | `NULL` | Set (advisory only — never blocks upload) when another active document shares the same vendor + invoice number |
| `deleted_at` | TIMESTAMPTZ | yes | `NULL` | Soft-delete marker: `NULL` = active/live document, a timestamp = "moved to trash at this time" |
| `uploaded_by` | UUID (FK → `users.id`, RESTRICT) | no | — | Who uploaded it (can't be deleted while documents reference them) |
| `uploaded_at` | TIMESTAMPTZ | no | `now()` | |
| `processed_at` | TIMESTAMPTZ | yes | `NULL` | When the pipeline finished (success or `needs_review`) |

**Status machine** (the `status` column's possible values, and how they flow):
```
queued → extracting_text → [ocr_processing] → [ai_extraction] → completed
                                                                → needs_review
                                                                → failed
```
- `queued`: waiting for the worker to pick it up.
- `extracting_text`: the worker is parsing text out of the file right now.
- `ocr_processing`: only entered if the file needed OCR (a scanned page, an image).
- `ai_extraction`: only entered if the cheaper deterministic extraction wasn't confident enough
  and the document is being sent to the AI (VLM) fallback.
- `completed`: fully processed. Text, thumbnail, and search index are ready; structured data may
  or may not be present depending on whether the document even looked like an invoice/receipt.
- `needs_review`: the document *looked* like it should have structured data (an invoice-shaped
  document), but neither the deterministic extraction nor the AI fallback was confident enough to
  accept. The document is still fully archived and searchable — this only affects the structured
  fields, never the ability to find or open the file.
- `failed`: something crashed and the retry budget (3 attempts) was exhausted.

### 2.4 `document_types` — the dynamic type catalog

Document types are **data, not code** — adding a new one is a database insert, not a code change.

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | **yes** | `NULL` | `NULL` = a system-wide type visible to every tenant (the 7 seeded types); non-`NULL` = a tenant-specific custom type |
| `name` | VARCHAR | no | — | e.g. `"invoice"` |
| `description` | TEXT | yes | `NULL` | |
| `json_schema` | JSONB | yes | `NULL` | An optional soft schema, used only to help score extraction confidence — never enforced strictly |
| `is_system` | BOOLEAN | no | `false` | True for the 7 seeded types |
| `created_at` | TIMESTAMPTZ | no | `now()` | |

**The 7 seeded system types:** `invoice`, `receipt`, `contract`, `report`, `letter`, `form`, `other`.

### 2.5 `document_templates` — learned extraction layouts (self-learning loop)

Captures a recognised document layout so future documents from the same source can be extracted
deterministically without re-inventing the extraction rules each time.

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `document_type_id` | UUID (FK → `document_types.id`, CASCADE) | no | — | |
| `name` | VARCHAR | no | — | |
| `fingerprint` | VARCHAR | no | — | A hash identifying "this layout" so future documents can be matched to it |
| `field_mappings` | JSONB | no | `{}` | The extraction rules learned for this layout |
| `status` | VARCHAR | no | `"candidate"` | `candidate` → `promoted` (proven reliable after enough examples) → `disabled` |
| `examples_count` | INTEGER | no | `0` | How many accepted extractions have used this template |
| `confidence` | REAL | yes | `NULL` | |
| `version` | INTEGER | no | `1` | |
| `sample_document_id` | UUID (FK → `documents.id`, SET NULL) | yes | `NULL` | One example document that produced this template |
| `created_at` / `updated_at` | TIMESTAMPTZ | no | `now()` | `updated_at` auto-refreshes on every row update |

### 2.6 `extractions` — full audit history of every extraction attempt

One row per attempt (not just the winning one) — deterministic, AI, or manual. This is what
powers the "needs review" queue and gives a complete, honest record of what the system tried.

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `document_id` | UUID (FK → `documents.id`, CASCADE) | no | — | |
| `template_id` | UUID (FK → `document_templates.id`, SET NULL) | yes | `NULL` | |
| `method` | VARCHAR | no | — | `"deterministic"` / `"vlm"` (the AI model) / `"manual"` (a human correction) |
| `model_name` | VARCHAR | yes | `NULL` | The AI model's name, when `method = "vlm"`; `NULL` otherwise |
| `output` | JSONB | yes | `NULL` | The extracted fields this attempt produced, or an error description if it failed |
| `confidence` | REAL | yes | `NULL` | |
| `status` | VARCHAR | no | — | `"accepted"` / `"low_confidence"` / `"corrected"` / `"skipped_budget"` (tenant was over its monthly AI budget) |
| `created_at` | TIMESTAMPTZ | no | `now()` | |

### 2.7 `processing_jobs` — pipeline execution tracking (one per document)

Not a work queue itself (that's Redis/RQ) — this is the **observability record** of what the
worker did with each document: how long it took, what stage it reached, how many retries.

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `document_id` | UUID (FK → `documents.id`, CASCADE) | no | — | |
| `status` | VARCHAR | no | `"queued"` | `queued` / `running` / `completed` / `failed` |
| `stage` | VARCHAR | yes | `NULL` | Which pipeline stage is currently running: `text_extraction` / `ocr_processing` / `deterministic_extraction` / `ai_extraction` |
| `attempts` | INTEGER | no | `0` | Incremented every time the worker picks this job up (retries included) |
| `error` | TEXT | yes | `NULL` | |
| `enqueued_at` | TIMESTAMPTZ | no | `now()` | |
| `started_at` | TIMESTAMPTZ | yes | `NULL` | |
| `finished_at` | TIMESTAMPTZ | yes | `NULL` | |
| `duration_ms` | INTEGER | yes | `NULL` | Wall-clock processing time |

### 2.8 `activity_events` — the audit trail / activity feed

Append-only log. Powers the dashboard's "recent activity" feed, the per-document History tab,
and the org-wide Settings audit log — all from one table.

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `type` | VARCHAR | no | — | One of: `upload`, `processing_complete`, `processing_failed`, `search`, `download`, `user_added`, `edit`, `trash`, `restore`, `permanent_delete`, `duplicate_detected`, `user_removed`, `role_changed` |
| `document_id` | UUID (FK → `documents.id`, SET NULL) | yes | `NULL` | Which document this event is about, if any |
| `document_name` | VARCHAR | yes | `NULL` | Snapshotted at event time (so the feed still reads correctly even if the document is later renamed or deleted) |
| `user_id` | UUID (FK → `users.id`, SET NULL) | yes | `NULL` | `NULL` for system-generated events (e.g. an automatic trash purge) |
| `user_name` | VARCHAR | no | — | Snapshotted display name, or `"system"` for automated events |
| `timestamp` | TIMESTAMPTZ | no | `now()` | |
| `meta` | TEXT | yes | `NULL` | Free-text extra context (an error excerpt, "auto-purged 3 documents", etc.) |

### 2.9 `api_keys` — reserved for future API-key authentication

Not yet wired to any live authentication path — the table exists so the schema is ready when
this feature is built.

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `name` | VARCHAR | no | — | Display label the user gives the key |
| `prefix` | VARCHAR | no | — | The key's visible prefix (e.g. `dw_abc123`), safe to show in the UI |
| `hashed_key` | VARCHAR | no | — | Only a hash is ever stored — the raw key is never persisted |
| `last_used_at` | TIMESTAMPTZ | yes | `NULL` | |
| `created_at` | TIMESTAMPTZ | no | `now()` | |

### 2.10 `ai_usage` — the AI (VLM) spending ledger

One row per call to the AI fallback tier. Summed per tenant per calendar month to enforce the
monthly token budget (`tenants.llm_monthly_token_cap`).

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `document_id` | UUID (FK → `documents.id`, SET NULL) | yes | `NULL` | |
| `model_name` | VARCHAR | yes | `NULL` | |
| `prompt_tokens` | INTEGER | no | `0` | |
| `completion_tokens` | INTEGER | no | `0` | |
| `total_tokens` | INTEGER | no | `0` | |
| `created_at` | TIMESTAMPTZ | no | `now()` | |

### 2.11 `tags` + `document_tags` — organisation labels

Two tables: the tag definitions themselves, and a many-to-many join table linking tags to
documents (this is the **real, active** tagging system — not the dead `documents.tags` array
column mentioned in §2.3).

**`tags`**

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `name` | TEXT | no | — | Unique per tenant |
| `color` | TEXT | no | `"#6B7280"` | Hex colour shown in the UI |
| `match` | TEXT | no | `""` | An auto-matching rule pattern (e.g. keywords to look for) |
| `matching_algorithm` | TEXT | no | `"any"` | How `match` is interpreted: `none` (manual-only), `any`, `all`, `literal`, `regex` |
| `is_insensitive` | BOOLEAN | no | `true` | Whether matching ignores case |
| `is_inbox_tag` | BOOLEAN | no | `false` | Marks this as the special "Inbox" tag shown prominently in the UI |
| `created_at` | TIMESTAMPTZ | no | `now()` | |

**`document_tags`** (join table)

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `document_id` | UUID (FK → `documents.id`, CASCADE) | no | — | |
| `tag_id` | UUID (FK → `tags.id`, CASCADE) | no | — | |

A `(document_id, tag_id)` pair can only appear once (unique constraint), so assigning the same
tag twice is a harmless no-op rather than an error.

### 2.12 `correspondents` — vendor/sender entities

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `name` | TEXT | no | — | Unique per tenant |
| `email` | TEXT | yes | `NULL` | Unique per tenant when set (`NULL` values don't count as duplicates of each other) — auto-populated when an email attachment's sender is linked, or set manually |
| `match` | TEXT | no | `""` | Same auto-matching-rule idea as tags |
| `matching_algorithm` | TEXT | no | `"any"` | |
| `is_insensitive` | BOOLEAN | no | `true` | |
| `created_at` | TIMESTAMPTZ | no | `now()` | |

### 2.13 `custom_fields` + `document_field_values` — user-defined metadata

Lets a tenant define their own typed fields (like a spreadsheet column) and attach values of
those fields to individual documents.

**`custom_fields`** (the field *definitions*)

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `name` | TEXT | no | — | e.g. `"PO Number"` |
| `field_type` | TEXT | no | — | `text` / `number` / `date` / `boolean` / `select` |
| `options` | JSONB | no | `[]` | The list of allowed values, only used when `field_type = "select"` |
| `position` | INTEGER | no | `0` | Display order |
| `created_at` | TIMESTAMPTZ | no | `now()` | |

**`document_field_values`** (the actual *values*, per document)

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `document_id` | UUID (FK → `documents.id`, CASCADE) | no | — | |
| `field_id` | UUID (FK → `custom_fields.id`, CASCADE) | no | — | |
| `value` | JSONB | yes | `NULL` | Stored as JSON so it can hold a string, number, boolean, or `null` regardless of `field_type` |

At most one value row exists per `(document_id, field_id)` pair — setting a value again
overwrites the existing row rather than creating a duplicate.

### 2.14 `document_type_fields` — predefined fields per document type

Added in migration `0015`. Lets an admin say "every `invoice` should show a PO Number field by
default" — links an existing `custom_fields` entry to one of the 7 fixed document-type strings.

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `document_type` | TEXT | no | — | One of the 7 fixed document-type strings (not a foreign key — kept as a plain string to match `documents.document_type`) |
| `field_id` | UUID (FK → `custom_fields.id`, CASCADE) | no | — | |
| `required` | BOOLEAN | no | `false` | Only affects the upload popup's soft prompt — never enforced as a hard rule by the API |
| `position` | INTEGER | no | `0` | Display order |
| `created_at` | TIMESTAMPTZ | no | `now()` | |

A `(tenant_id, document_type, field_id)` triple can only appear once.

### 2.15 `saved_views` — persisted filter presets

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `name` | TEXT | no | — | |
| `filter_state` | JSONB | no | `{}` | The entire saved filter/sort/display configuration, as one JSON blob |
| `is_default` | BOOLEAN | no | `false` | Whether this view loads automatically |
| `created_at` | TIMESTAMPTZ | no | `now()` | |

### 2.16 `document_shares` — public, time-limited share links

| Column | Type | Nullable | Default | Meaning |
|---|---|---|---|---|
| `id` | UUID (PK) | no | — | |
| `tenant_id` | UUID (FK → `tenants.id`, CASCADE) | no | — | |
| `document_id` | UUID (FK → `documents.id`, CASCADE) | no | — | |
| `token` | VARCHAR(64) | no | — | **Globally unique** (not per-tenant — a public visitor has no tenant context, so lookup can only be by token). Generated with `secrets.token_urlsafe(32)`; the token itself, being unguessable, *is* the authorization for viewing the shared file — there's no separate password |
| `created_by` | UUID (FK → `users.id`, SET NULL) | yes | `NULL` | |
| `expires_at` | TIMESTAMPTZ | no | — | Required at creation time, capped to 1–30 days in the future |
| `created_at` | TIMESTAMPTZ | no | `now()` | |

---

## 3. How the tables relate (plain-English map)

```
tenants  (root — one row per customer)
  │
  ├── users                  (who's on the team)
  │
  ├── documents               (the actual archive — the biggest, most-connected table)
  │     ├── document_types        (what KIND of document — dynamic catalog)
  │     ├── document_templates    (a learned layout, for repeat-format documents)
  │     ├── extractions           (every extraction ATTEMPT for this document — full history)
  │     ├── processing_jobs       (pipeline execution tracking for this document)
  │     ├── document_tags → tags  (labels attached to this document)
  │     ├── correspondents        (the vendor/sender this document is linked to)
  │     ├── document_field_values → custom_fields   (custom metadata values)
  │     └── document_shares       (public share links pointing at this document)
  │
  ├── custom_fields            (field DEFINITIONS — reused across many documents)
  ├── document_type_fields     ("every invoice should show these fields by default")
  ├── activity_events          (audit trail — references documents/users loosely, never blocks)
  ├── ai_usage                 (AI spending ledger, tied to documents)
  ├── api_keys                 (reserved, not yet used)
  └── saved_views              (personal filter presets, standalone — no document link)
```

Every arrow above ultimately traces back to a `tenant_id` on the child table, and Postgres RLS
is what actually prevents one tenant's rows from ever being visible in another tenant's session
— the relationships shown here are about *what points to what*, not about who is allowed to see it.

---

## 4. Notable indexes

| Index | Table | Type | Why it exists |
|---|---|---|---|
| `ix_documents_search_tsv` | `documents` | GIN | Powers full-text search (`@@` operator on `search_tsv`) |
| `ix_documents_filename_trgm` | `documents` | GIN (trigram) | Powers fuzzy/typo-tolerant filename search |
| `ix_documents_extracted_gin` | `documents` | GIN (jsonb_path_ops) | Powers filtering inside the `extracted_data` JSON |
| `ix_documents_tenant_total_amount` | `documents` | B-tree | Amount-range filters |
| `ix_documents_tenant_vendor` | `documents` | B-tree | Vendor filter |
| `ix_documents_tenant_deleted_at` | `documents` | B-tree | Trash-view queries |
| `ix_documents_tenant_id` | `documents` | B-tree | Every tenant-scoped list query |
| every `*_tenant_id` index | (every table) | B-tree | RLS filters on `tenant_id` on almost every query — this is the single most important index across the whole schema |
| `uq_tags_tenant_name`, `uq_correspondents_tenant_email`, etc. | various | unique | Prevents duplicate names/emails per tenant |
| `uq_document_shares_token` | `document_shares` | unique | Global, since the public lookup has no tenant context |

---

## 5. Row-Level Security (RLS) — the isolation mechanism, concretely

Every tenant-owned table carries a policy shaped like this:

```sql
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;  -- applies even to the table owner

CREATE POLICY tenant_isolation_documents ON documents
  USING (
    tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
  )
  WITH CHECK (
    tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
  );
```

**Reading this in plain English:**
- `current_setting('app.current_tenant', true)` reads a per-connection variable the application
  sets at the start of every request (`true` here means "don't error if it was never set — just
  return an empty string").
- `NULLIF(..., '')` turns that empty string into a real SQL `NULL` when the variable was never
  set.
- `tenant_id = NULL` is never true in SQL (comparing anything to `NULL` gives `NULL`, which is
  treated as "no match") — so if the application forgets to set the tenant variable, **every
  query returns zero rows** instead of leaking data from every tenant. This is the "fail-closed"
  property: a bug looks like "nothing shows up," never "the wrong tenant's data shows up."
- `USING (...)` filters what existing rows are visible to `SELECT`/`UPDATE`/`DELETE`.
- `WITH CHECK (...)` rejects any `INSERT`/`UPDATE` that would try to write a row for a *different*
  tenant than the one currently set.

The `tenants` table itself uses `id = ...` instead of `tenant_id = ...` (it doesn't have a
`tenant_id` column — it *is* the tenant).

---

## 6. Migration history

| Revision | What it did |
|---|---|
| `0001` | Initial 9 tables + Postgres extensions (`pgcrypto` for UUID generation, `pg_trgm` for fuzzy search) + core indexes |
| `0002` | Turned on RLS + `FORCE ROW LEVEL SECURITY` on every tenant-owned table, one policy per table |
| `0003` | Seeded the 7 system document types |
| `0004` | Granted table access to the `authenticated` Postgres role (the RLS-respecting role the live app actually connects as) |
| `0005` | Fixed the RLS policy to handle Supabase returning `''` instead of `NULL` for an unset session variable |
| `0006` | Added `ai_usage` + `tenants.llm_monthly_token_cap` (the AI spending budget) |
| `0007` | Added universal-ingestion columns to `documents`: `checksum`, `title`, `document_date`, `thumbnail_key` |
| `0008` | Added `documents.deleted_at` (soft-delete / trash) |
| `0009` | Created `correspondents`, `tags`, `document_tags`, `documents.correspondent_id` |
| `0010` | Created `custom_fields`, `document_field_values` |
| `0011` | Created `saved_views` |
| `0012` | Promoted `vendor`/`invoice_no`/`total_amount`/`currency` out of the `extracted_data` JSON blob into real typed columns; added `duplicate_of_document_id`; backfilled existing rows |
| `0013` | Created `document_shares` (public share links) |
| `0014` | Added `correspondents.email` + a per-tenant unique constraint |
| `0015` | Created `document_type_fields` (predefined custom fields per document type); seeded a starter set of fields for every existing tenant |
| `0016` | Added `tenants.trash_retention_days` + `tenants.trash_last_purged_at` (trash auto-retention) |

### Running migrations

```bash
cd backend
alembic upgrade head       # apply every migration up to the current one
alembic current            # check which revision the database is actually on
alembic downgrade -1       # roll back exactly one migration (rarely needed)
```

Migrations connect using `ALEMBIC_DATABASE_URL` (a **direct** database connection, port 5432,
as the `postgres` superuser — needed because creating/altering tables requires privileges the
live app's restricted `app_user` role doesn't have). The live application itself connects using
`DATABASE_URL` (Supabase's **transaction pooler**, port 6543, as the restricted `app_user` role) —
these are deliberately two different connection strings for two different purposes.

**Never edit a migration file that has already been applied anywhere** (locally, in staging, or
in production) — write a new migration instead, even to fix a mistake in an old one.
