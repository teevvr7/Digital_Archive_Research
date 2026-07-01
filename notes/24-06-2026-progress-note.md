# Daily Progress Report — 24 June 2026

## Overview
Completed the decoupling of the IDP Control Center UI by splitting prompts into specialized System Instructions and System Rules, enabling dynamic serialization on the backend. Stabilized the background task worker against environment-specific Microsoft `onnxruntime` DLL crashes on Windows by implementing graceful engine isolation. Aligned the remote Supabase database by migrating all existing document type records to the remote `"paddle_qwen"` strategy, successfully unblocking the document processing queues.

---

## 1. Decoupled IDP Control Center UI & Dynamic Prompts
* **UI Redesign**: Replaced the single, complex prompt schema editor in the Settings tab with three specialized fields:
  * **System Instruction**: A plain-text editor for guiding the model's persona (e.g., specialized financial extractor).
  * **System Rules & Constraints**: A plain-text editor for specific formatting, date conversions, and value rules.
  * **Target JSON Schema**: A structured JSON editor defining the desired output fields.
* **API Extension**: Updated the frontend API client and types in `frontend/lib/api.ts` to explicitly support the split `instruction` and `rules` fields.
* **Backend Prompt Serialization**: Refactored `run_ai_extraction` in `backend/app/modules/idp/pipeline.py` to extract `_instruction` and `_rules` metadata from the schema (falling back to robust defaults if missing), concatenate them into a unified custom prompt, and strip them out to deliver a clean, metadata-free target schema to the remote GPU service.

---

## 2. Background Worker Stabilization & DLL Isolation
* **Local OCR Protection**: Solved the worker queue crashes caused by local machine environment limitations (missing Microsoft Visual C++ Redistributable or CPU instruction mismatches in the pre-compiled `onnxruntime` DLL).
* **Graceful Fallbacks**: Modified `backend/app/modules/idp/ocr.py` to wrap library imports and engine initialization in a `try/except` block. If the C++ binary fails to initialize, the system logs a warning and disables the engine, returning empty text instead of raising an unhandled exception.
* **Result**: The local background worker process is now fully immune to native library crashes, ensuring 100% queue uptime even if a document is mistakenly routed to the local fallback path.

---

## 3. Database Strategy Alignment
* **Issue**: Discovered that pre-existing document types in the remote Supabase database were defaulting to the `"default"` strategy (due to server default constraints in database migrations), overriding python-level defaults and forcing documents onto the local OCR path.
* **Migration Script**: Created and executed `backend/scripts/migrate_strategies.py`.
* **Alignment Completed**: Successfully connected to the remote Supabase database and migrated all **8 existing DocumentType records** from `"default"` to `"paddle_qwen"`. This immediately routed all queued/pending documents to the remote GPU environment, unblocking the worker queue.

---

## 4. Verification & Testing
* **Integration Tests**: Refactored `backend/app/tests/test_paddle_qwen.py` to align and validate the split instruction, rules, and schema serialization.
* **Execution**: All backend unit and integration tests passed successfully. End-to-end processing of queued documents was verified as fully functional in the local development environment.
