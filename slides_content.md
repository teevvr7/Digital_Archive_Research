# Presentation Slides: DataWiz Digital Archive
**Date of Record: 15 July 2026**

This document contains slide-by-slide content structures for presenting the DataWiz architecture, database engines, data pipelines, security enforcement, and future roadmap.

---

## Slide 1: Title Slide
### DataWiz Digital Archive
*Intelligent Document Processing & Multi-Tenant Archival System*

* **Sub-title**: $0/Month Infrastructure Cost Design for Small-to-Medium Businesses (SMBs)
* **Author / Presenter**: DataWiz Technical Architecture Team
* **Core Value**: Enterprise-grade document extraction, indexing, and search without expensive third-party infrastructure.

---

## Slide 2: The Core Problem & Design Philosophy
### The 10–15% AI Exception Rule
*How we process documents at near-zero fixed infrastructure cost.*

* **The Problem**: Naive AI document processing relies on expensive GPU calls for *every single document*, leading to unsustainably high monthly bills.
* **The Solution**: 85% to 90% of documents can be processed using free or local CPU methods. We treat the AI layer (Qwen-VL) strictly as an *exception handler*.
* **Cost Cascade (Cheapest First)**:
  1. **Digital PDF**: Copy text layer directly via `PyMuPDF` (Free, instant).
  2. **Template Match**: Extract metadata fields using coordinates from matches (Free, deterministic).
  3. **Scanned PDF / Image**: Local ONNX-based `RapidOCR` or remote `PaddleOCR` (Cheap, CPU).
  4. **Dynamic AI Extraction**: Remote GPU-bound `Qwen-VL` (VLM) (Only when required).
* **Target Operating Budget**: ~$0/month utilizing Supabase free tier and Lightning AI Studio GPU (suspended when idle).

---

## Slide 3: High-Level System Architecture
### Modular & Scalable Micro-Service Layout

* **Frontend Page App**: Single-page application built on Next.js, TailwindCSS, and Lucide React.
* **Backend Web Gateway**: Async FastAPI (Python) routing, executing JWT verification and Postgres session config.
* **Asynchronous Workers Queue**: Redis Queue (`rq`) worker pool executing background ingestion, OCR, and AI tasks.
* **Remote AI Server**: Dedicated FastAPI container housing PaddlePaddle layout parsers and the vLLM engine.
* **Cloud Infrastructure**: Supabase managed services (PostgreSQL, Auth admin controls, S3 storage).

---

## Slide 4: Multi-Tenant Security & Transaction Isolation
### Row-Level Security (RLS) Enforced at the Core Database Layer

* **No App-Level Leaks**: Tenant separation is guaranteed by the database engine, not by backend code.
* **Transaction GUC Variable**:
  * Every API call opens a transaction block and runs: `SET LOCAL app.current_tenant = '{tenant_id}'`.
  * The GUC resets automatically on transaction completion, leaving zero state leakage.
* **Fail-Closed RLS Policy**:
  * Policies evaluate: `USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)`.
  * If the session GUC is empty, `NULLIF` evaluates to `NULL` and queries automatically fail closed, returning exactly 0 rows.
* **Object Storage Security**: Files are saved at `tenants/{tid}/docs/{id}.ext`. The API issues signed access URLs with a 5-minute TTL; public endpoints never stream raw bytes.

---

## Slide 5: Database Schema (Part 1 - Core Entities)
### 16 Isolated Tables Enforced by PostgreSQL RLS

* **`tenants` & `users`**: Root tenant configurations and email profiles linked to Supabase Auth UUIDs.
* **`documents`**:
  * Central file register: stores status (`queued`, `completed`, `failed`), page count, checksums, title, and metadata.
  * Employs soft-deletion via the `deleted_at` timestamp.
* **`document_types`**: Stores soft validator schemas (invoice, receipt, contract, report, form, etc.).
* **`document_templates`**: Holds learned layouts and bounding-box coordinates for matching vendor documents.
* **`processing_jobs`**: Logs pipeline stage logs, duration, and error codes for diagnostics.
* **`extractions`**: Audit trail for every VLM parsing run.
* **`activity_events`**: Append-only user log backing the dashboard feed.

---

## Slide 6: Database Schema (Part 2 - Metadata & Rule Engines)
### Relational Tagging, Auto-Matching, and Custom Fields

* **`tags` & `document_tags`**: Per-tenant labels catalog and M2M join mapping. Replaces the deprecated flat string array.
* **`correspondents`**: Sender/Vendor classification catalog. Links documents to entities automatically.
* **`custom_fields` & `document_field_values`**: Flexible custom metadata columns (text, number, date, boolean, select) allowing manual user corrections.
* **`saved_views`**: Scopes query criteria into saved workspace filters.
* **`ai_usage`**: Metering database that tracks completion tokens and prompt tokens. Sums monthly tokens per tenant to enforce monthly budget caps.

---

## Slide 7: Ingestion Pipeline - Stage 1 (Text) & Stage 2 (OCR)
### Free Text Extraction & CPU/GPU OCR Fallbacks

* **Stage 1: Text Ingestion (`PyMuPDF`)**:
  * Checks for pre-extracted digital text layers.
  * If whitespace character count satisfies `len(chars) >= max(16, 8 * page_count)`, text is loaded directly. This bypasses OCR and VLM completely (**Digital Read** mode).
* **Stage 2: OCR Fallback (`PaddleOCR` / `RapidOCR`)**:
  * If the text layer is empty or sparse, the file is rasterized to PNGs.
  * Sends images to `PaddleOCR` (remote GPU server) or runs local ONNX `RapidOCR` client.
  * Computes line-by-line mean confidence scores.

---

## Slide 8: Ingestion Pipeline - Stage 3 (AI Structuring)
### Dynamic VLM Extraction & Robust Error Correction

* **Deterministic Template Cascade**:
  * Compares layout fingerprints against promoted tenant templates. If a match is found, fields are parsed deterministically via coordinates without VLM queries (**Deterministic Match**).
* **Two-Phase VLM Prompting (Qwen-VL)**:
  * If no template matches, the document text/images are sent to Qwen-VL.
  * *Phase 1 (Header)*: Extracts top-level fields (vendor, total, date, currency).
  * *Phase 2 (Line Items)*: Iterates through text chunks to parse granular tables.
* **JSON Bracket-Repair Stack Parser**:
  * If VLM outputs are truncated, the parser closes open strings, removes trailing commas, deletes dangling keys, and closes brackets in reverse order.
* **Rules Engine**: Links tags and correspondents based on keyword match expressions.

---

## Slide 9: Typo-Tolerant Search Engine
### Three-Tier Single-Query Search matching FTS & Trigrams

* **No Search Cluster Required**: All search matches are computed in one Postgres SQL query, keeping operations light.
* **Search Execution Flow**:
  1. **Tier 1 (Exact FTS)**: Evaluates query using `websearch_to_tsquery('english', q)`. Stemming is applied automatically.
  2. **Tier 2 (Autocomplete FTS)**: Splits terms into prefix tokens (`tok:*`) to match characters as the user types.
  3. **Tier 3 (Typo-Tolerance)**: Uses `pg_trgm`'s `word_similarity()` with a similarity threshold of `0.2` (e.g. searching `"invioce"` matches `"invoice_2026.pdf"`).
* **Excerpt Highlight**: Employs `ts_headline` to return matching terms wrapped in CSS-highlighted `<mark>` tags.

---

## Slide 10: Dynamic Spreadsheet Export Center
### Granular Line-Item Flattening & Key Normalisation

* **Dynamic Columns Discovery**: Queries defined schemas in template mappings or type definitions first, ensuring the picker loads columns instantly even if no documents exist in the database yet.
* **Cascading Dropdowns**: Filters lock automatically (selecting a template locks doc type; changing type narrows template options).
* **Key Normalisation Layer**: Maps variable extracted names (`vendor_name`, `supplier`, `company_name`) into unified canonical columns (`vendor`).
* **Line Item Modes**:
  * **Summary Mode**: Collapses rows to one row per document, displaying an `itemCount` column.
  * **Expanded Mode**: Flattens nested item/sub-item arrays into individual rows, repeating doc headers, and adds depth indentation markers.
* **Sub-Object Serialization**: Converts nested sub-structures (addresses, arrays) to valid JSON strings in the CSV output.

---

## Slide 11: Document Modality & UI Badges
### Operational Visibility for Ingestion & Modality Paths

Every processed document displays two indicators in its details header:
1. **Source Modality** (Ingestion Path):
   * **Digital Read** (Slate): Native digital text parsed.
   * **GPU OCR (Paddle)** (Indigo): Handled by PaddleOCR server.
   * **Local OCR (Rapid)** (Cyan): CPU-bound RapidOCR fallback.
2. **Extraction Strategy** (Structured Parsing):
   * **Deterministic Match** (Emerald): Scanned template matched, zero AI cost.
   * **VLM Extraction** (Purple): Dynamic AI parsing.
   * **Manually Verified** (Amber): Values reviewed and saved by a user.

---

## Slide 12: In-Production Verification & Testing
### 243 Tests Verifying Multi-Tenancy & Integrity

* **Total Test Coverage**: **243** active tests running in both local and CI pipeline environments.
* **Technical Test Modules**:
  * `test_contract_camelcase.py`: Validates camelCase API serialization.
  * `test_tenant_isolation.py`: Seeds multiple tenants to prove that cross-tenant queries fail closed.
  * `test_ai_extraction.py`: Validates prompt tokens budget limits and JSON bracket-repair routines.
  * `test_export_spreadsheet.py`: Mock database unit tests verifying metadata selectors, preview modes, and CSV export.
* **Quality Assurance**: Compiles cleanly with zero TypeScript errors (`npx tsc --noEmit`).

---

## Slide 13: What is Already Built (Project Status)
### Stable & Core Capabilities Implemented

* **Multi-Tenant RLS Core**: Total database isolation.
* **Dual Ingestion Modi**: Automatic path detection.
* **Deterministic Layout Templates**: Fingerprint coordinate matcher.
* **Soft Delete Trash Bin**: 30-day recycle trash management with S3 cleaner jobs.
* **Rules Engine Classifier**: Automates correspondent assignment and tag linking.
* **Editable Custom Fields**: Add custom metadata structures and edit incorrect values.
* **Accounting Spreadsheet center**: Granular line-item/summary export sheets.
* **Fuzzy Typo-Tolerant Search**: Searches content and filename text with keyword highlights.

## 14. Slide 14: Upcoming Milestones (Short-Term Focus)
### Refining the Core Processing & Classification Heuristics

* **Spreadsheet Center Usability**:
  * Implement table cell overflow wrapping constraints, responsive layout tweaks, and clear-filters buttons.
* **Intelligent Document Auto-Classification**:
  * Build layout-fingerprint and keyword analysis models to automatically assign document types (e.g., *invoice*, *receipt*, *contract*) upon initial file ingestion.
  * Reduces user friction by eliminating manual file profiling steps in the drag-and-drop zone.

---

## 15. Slide 15: Next Phase — RAG Ingestion & Database Preparation
### Multi-Tenant Vector Database & Embedding Pipeline

* **Generic JSON-to-Markdown Serialiser**:
  * Serialises dynamic and schema-agnostic extraction data JSONB into highly structured, hierarchy-preserving Markdown.
  * Avoids hardcoded field mapping while providing embedding models with readable natural language contexts.
* **pgvector Database Schema additions**:
  * Run Alembic migration to create the `document_chunks` table, isolated per tenant via Postgres RLS.
  * Embed an `HNSW` index for sub-millisecond vector similarity search.
* **On-Worker Embeddings Processing**:
  * Background worker processes segment raw text into sliding window chunks, calculating 384-dimensional vector embeddings locally using sentence-transformers (`all-MiniLM-L6-v2`).
* **Swappable LLM Providers**:
  * Uses the OpenAI-compatible standard Python client to call Qwen-VL, self-hosted vLLM, OpenAI, Groq, or local Ollama endpoints dynamically via env parameters.

---

## 16. Slide 16: Next Phase — RAG Retrieval & Prompting Logic
### Similarity Search, VLM Synthesis, and Metric Evaluation

* **RLS Vector Search Query**:
  * Retrieves candidate chunks via cosine similarity matching on the current tenant vector space.
* **VLM Prompt Synthesis**:
  * Contextually wraps the top-$k$ retrieved Markdown chunks inside system instruction envelopes.
  * Passes contexts directly to the pre-loaded Qwen-VL model to compile semantic chatbot answers citing source invoice IDs.
* **Automated Evaluation Metrics**:
  * Measures retrieval performance against a curated Q&A ground-truth dataset (`Hit Rate@5` and `MRR@5` metrics) to optimize chunking configurations.
* **Chat Feedback Value Loop**:
  * Streams conversation logs, records response latencies, and gathers user thumbs-up/down feedback to build quality dashboards.
