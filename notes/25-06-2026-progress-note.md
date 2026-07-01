# Daily Progress Report — 25 June 2026

## Overview
Designed a production-grade, environment-toggled pipeline debugger for the remote GPU server to trace OCR and Qwen data flows without log pollution. Restructured the system prompts to ensure Qwen-VL strictly adheres to custom system instructions and rules. Traced and diagnosed a critical schema resolution flaw in the background worker queue, and designed a metadata string serialization strategy to bypass PostgreSQL `JSONB` sorting, guaranteeing the exact admin-defined JSON schema order is preserved.

---

## 1. Remote GPU Server Debugger & Prompt Polish
* **Togglable Pipeline Debugger**: Designed a developer-controlled debugging tool inside `remote_paddle_server.py` using standard environment variables (`DEBUG_RAW_OCR`, `DEBUG_CLEANED_OCR`, `DEBUG_FULL_PROMPT`, `DEBUG_RAW_RESPONSE`). This allows developers to selectively trace each stage of the extraction pipeline on the GPU console, keeping production logs clean and compliant.
* **Instruction Positioning Optimization**: Restructured the system instructions in the remote GPU server to place the custom instructions and rules at the very top of the prompt using visual dividers (`=== CRITICAL EXTRACTION INSTRUCTIONS ===`) before the target schema. This ensures Qwen-VL prioritizes the custom rules during generation, preventing it from ignoring user settings.
* **Model Alignment**: Updated the fallback configurations to use your active model `Qwen3-VL-4B-Instruct-FP8`.

---

## 2. Diagnostics: Schema Resolution Flaw
* **Flaw Tracing**: Investigated why custom instructions and rules saved in the IDP Control Center were ignored by the pipeline. 
* **Diagnosis**: When the admin saves settings, the API stores them in a tenant-specific `DocumentTemplate` with `status="promoted"`. However, because a new document upload has no layout fingerprint yet, its `doc.template_id` is `None`. The background worker (`jobs.py`) and orchestrator (`pipeline.py`) were falling back directly to the global, system-default `DocumentType` schema, bypassing your custom template entirely.
* **The Fix**: Designed a prioritized template resolution flow that checks for a tenant's promoted template if `doc.template_id` is `None` before falling back to the static `DocumentType`.

---

## 3. Dynamic JSON Key Ordering (LLM Strategy)
* **The Challenge**: PostgreSQL `JSONB` columns normalize and alphabetically sort keys, destroying the custom sequence defined by the admin in the UI. In LLM extraction, a linear, top-down key sequence is crucial for guiding the model's reading flow and maximizing extraction accuracy.
* **The Solution**: Developed a **Metadata String Serialization** approach. When saving, the backend serializes the ordered schema dictionary into a JSON string (`_original_schema_str`) and stores it as a plain string inside the `JSONB` column. Because it is a string, PostgreSQL does not reorder it. When loaded by the worker or UI, the backend parses the string, restoring the exact admin-defined key order dynamically.

---

## 4. Fail-Fast Mechanism
* **Mock Fallback Control**: Designed a strict fail-fast mechanism. Added the `allow_mock_fallback` configuration parameter (defaulting to `False`). If the remote GPU server is offline or fails, the local worker will immediately raise a visible exception and fail the document, rather than silently returning mock data.
