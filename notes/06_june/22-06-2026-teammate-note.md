# Project Update Note — 22 June 2026

Hi! I have integrated the custom `paddle_qwen` extraction strategy (PaddleOCR-VL + Qwen-VL with mathematical validation) into the digital archiving pipeline. This was built using a **pluggable architecture** to keep our strategies isolated and protect your default VLM cascade from any regression.

Here are the key updates and details you need to know about:

---

## 1. Action Items for You
1. **Apply Database Migration**: Run the Alembic upgrade to add the new strategy column to your local tables:
   ```bash
   cd backend
   alembic upgrade head
   ```
2. **Environment Variables**: I added default variables to `config.py` for PaddleOCR and Qwen LLM. If you want to connect the worker to active GPU instances of these models, add them to your local `backend/.env`:
   ```env
   PADDLE_OCR_URL=http://localhost:8000/v1
   PADDLE_OCR_MODEL=PaddlePaddle/PaddleOCR-VL
   QWEN_LLM_URL=http://localhost:8001/v1
   QWEN_LLM_MODEL=Qwen2.5-1.5B
   ```
   *If these are left out or point to default localhost servers, the worker uses mock predictions. This allows you to test the pipeline locally offline.*

---

## 2. Pluggable Routing & Strategy Selector
* **DB-Driven Selection**: Rather than reading static environment variables, the worker resolves `extraction_method` from the database (on the document's template or type record).
* **Isolation & Fallbacks**: The column defaults to `"default"`. Your original cost cascade (`run_default_extraction`) executes unchanged for all system and user documents unless you explicitly change their configuration to `"paddle_qwen"`.
* **Graceful Degradation**: `paddleocr` is lazy-imported. If you run the worker without installing `paddleocr`, the code detects this and falls back to Mock Mode rather than throwing an import error.

---

## 3. Frontend & UI Changes
* **IDP Control Center Tab**: I added an **IDP Control Center** tab under Settings (`frontend/app/(app)/settings/page.tsx`) where you can:
  * Select document classifications.
  * Swap extraction strategies between *Teammate VLM Cascade* and *PaddleOCR-VL + Qwen-VL*.
  * Customize target JSON schemas and prompts.
* **Token Refresh Fix**: Added `supabase.auth.refreshSession()` on first login to update browser token claims immediately. This prevents the `403 Account not associated with a tenant` race condition on redirect.
* **Status Badges Alignment**: Mapped `"needs_review"` and `"success"` statuses inside `types/index.ts`, `status-badge.tsx`, and `globals.css` to prevent `TypeError` crashes when the UI encounters documents processed by alternative pipelines.

---

## 4. Backend Code Additions
* **Config Routers**: Registered `/api/idp/config` GET/POST endpoints in `main.py` for tenant-isolated template customization.
* **Test Suite**: Created `backend/app/tests/test_paddle_qwen.py` containing complete unit tests. All tests run and pass without requiring external model endpoints.
* **Core Dependency**: Added `beautifulsoup4` to backend dependencies (`pyproject.toml`) for parsing layouts.
