# Daily Progress Report — 22 June 2026

## Overview
Successfully implemented dynamic database-driven Intelligent Document Processing (IDP) strategy switching and constructed a premium, interactive **IDP Control Center** settings tab in the frontend. This setup lets different tenants configure custom prompts, schemas, and model strategies (`default` vs. `paddle_qwen`) in real-time without server restarts, keeping the baseline system fully backward-compatible.

---

## 1. Database Schema & Migrations
* **Alembic Migration**: Created and successfully ran Alembic migration `eebe53429cbf_add_extraction_method_column.py`.
* **Database Columns**: Added `extraction_method` column (`String`, non-nullable, default `"default"`) to the `document_types` and `document_templates` tables. This column determines whether a document goes through the teammate's default VLM cascade or the custom `paddle_qwen` pipeline.

---

## 2. Pluggable IDP Pipeline Integration
* **Orchestration Dispatcher (`pipeline.py`)**: Modified `run_ai_extraction` to dynamically fetch the extraction strategy:
  1. Resolves `extraction_method` from the document template if a promoted one exists for the tenant.
  2. Falls back to the document type default configuration.
  3. Dispatches to the `paddle_qwen` strategy or your teammate's default cascade.
* **PaddleOCR-VL + Qwen-VL Strategy (`paddle_qwen.py`)**:
  * **Table Parsing**: Implemented HTML-to-Markdown table conversions (`BeautifulSoup`) and OCR text cleaning.
  * **Model Calling**: Configured OpenAI compatible client to target Qwen-VL/LLM.
  * **Math & Quality Guard**: Integrated mathematical subtotal + tax = total validation, auto-raising `requires_human_review = True` and recording validation errors if a mismatch exceeds 0.02, or if the vendor name is missing.
  * **Offline Mocks**: Embedded mock predictors to seamlessly run extraction dry-runs if GPU endpoints are cold or offline during local debugging.

---

## 3. Configuration & Developer APIs
* **Config Router (`config_router.py`)**: Created:
  * `GET /api/idp/config`: Lists all system and tenant-specific document types with active configs.
  * `GET /api/idp/config/{id}`: Resolves single active config.
  * `POST /api/idp/config/{id}`: Upserts tenant-promoted `DocumentTemplate` overrides on-the-fly.
* **Developer Swagger Helpers**:
  * Added `custom_openapi` schema fixes in `main.py` so Swagger UI displays file browser pickers (converts binary octet-streams properly).
  * Added `POST /api/documents/single` route to support instant uploads.

---

## 4. UI Dashboard & Settings Integration
* **IDP Control Center Page**: Integrated the **IDP Control Center** tab under settings in `frontend/app/(app)/settings/page.tsx`:
  * Lists document types (Invoice, Receipt, Contract, etc.).
  * Real-time toggling of extraction pipelines (Teammate VLM vs. Paddle-Qwen).
  * Editable textareas for target JSON Schema and Prompt Hints.
  * Loading, saving, and validation states with micro-animations.
* **Authentication Bootstrap Fix**: Wired `supabase.auth.refreshSession()` on the login page after `apiBootstrap()`. This immediately refreshes the browser's JWT token to include the newly assigned `tenant_id` claims, preventing 403 Forbidden errors.
* **UI Resilience**: Mapped `"needs_review"` and `"success"` document statuses in `types/index.ts`, `status-badge.tsx`, and `globals.css` to prevent runtime `TypeError` crashes.

---

## 5. Verification & Testing
* **Test Suite**: Created `backend/app/tests/test_paddle_qwen.py` testing HTML parsing, JSON recovery, config routers, and strategy dispatching.
* **Test Results**: All **60 tests passed** successfully.
* **Type Safety**: Ran Next.js TypeScript compilation checks (`npx -p typescript tsc --noEmit`) resulting in **0 compile errors**.
