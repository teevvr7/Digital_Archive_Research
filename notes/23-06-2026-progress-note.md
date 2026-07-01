# Daily Progress Report — 23 June 2026

## Overview
Refactored the pluggable Intelligent Document Processing (IDP) strategy from a multi-network-hop model into a **single-network-hop Unified Remote Service (Option A)**. Resolved a blocking Windows environment issue involving an `onnxruntime` DLL load crash by modifying the background worker to execute early strategy resolution and bypass local OCR. All 61 backend unit tests pass successfully.

---

## 1. Unified Remote Service Architecture (Option A)
* **Goal**: Offload both PaddleOCR-VL and Qwen-VL models, plus the document pre/post-processing logic, onto the remote Lightning AI GPU server.
* **Orchestration Offloaded**: Bypassed CPU-heavy PDF page rasterization, layout tags cleaning, and OpenAI compatible completions on the local machine.
* **Network Optimization**: Reduced the payload round-trips from $N+1$ (where $N$ is the page count) down to **exactly 1 unified POST request**.

---

## 2. Code Implementations & Refactorings

### Remote GPU Server Setup
* Designed the FastAPI wrapper script `remote_paddle_server.py` to run on the Lightning AI GPU.
* The script handles incoming file uploads, uses PyMuPDF (`fitz`) to rasterize pages if PDF, queries local PaddleOCR-VL on port `8000`, sanitizes HTML tables to Markdown, runs local loopback queries to Qwen-VL on port `8001`/`8003`, audits subtotals/taxes, and returns validated JSON data, clean OCR text, and page counts.

### Local Client Refactoring (`paddle_qwen.py` & `pipeline.py`)
* Refactored `run_remote_paddle_qwen_extraction` to make a single REST call to `settings.paddle_ocr_url/v1/extract` using `httpx`.
* Modified the dispatcher in `pipeline.py` to parse the 4-tuple return payload `(validated_json, raw_content, ocr_text, page_count)` and save the remote text directly to the SQLAlchemy `Document` database model. This ensures full-text search indexing is populated correctly.

---

## 3. Early Strategy Resolution & Bug Fixes

### Local Worker Queue Hang (onnxruntime ImportError)
* **Problem**: Scanned PDF or image uploads were hanging in the worker queue and failing. The logs revealed a Windows-specific DLL crash: `ImportError: DLL load failed while importing onnxruntime_pybind11_state`.
* **Root Cause**: The worker ran the local OCR extraction stage `run_extraction()` (which imports `rapidocr-onnxruntime` and `onnxruntime`) *before* checking the database strategy. The worker crashed before reaching the remote dispatcher block.
* **Solution**: Rewrote `process_document` in `jobs.py` to resolve the strategy from the database at the very start of the worker thread. If the document strategy is `"paddle_qwen"`, the worker completely bypasses the local `run_extraction()` step, avoiding the broken local DLL call and resolving queue hangs.

---

## 4. Verification & Testing
* **Test Suite Alignment**: Updated `test_paddle_qwen.py` to mock the single unified API response payload.
* **Pytest Verification**: Executed the entire test suite on the local Windows environment: **61/61 tests passed successfully**.
