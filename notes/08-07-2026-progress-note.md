# Daily Progress Report — 8 July 2026

## Overview
Successfully implemented dynamic modality badging upgrades across the backend/frontend boundaries, conducted database schema hardening (dropping deprecated columns via migration), resolved sub-item rendering hierarchies in the line item extraction details view, and conducted research on competitor architectures and SMB use cases.

---

## 1. Database Schema Hardening & Cleanup
* **Dropped Columns**: Removed deprecated `layout_fingerprint` and `tags` (string array) columns from the `documents` table via a new migration revision `2f0fd6e40db5`.
* **Index Preservation**: Confirmed that the GIN, FTS (Full-Text Search), and Trigram indexes remain fully intact.
* **Test Maintenance**: Cleaned up mock tag assignments in [test_file_management.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/backend/app/tests/test_file_management.py) and verified that all 227 tests pass cleanly.

---

## 2. Dynamic Modality Badging Upgrades
* **Backend Serialization**: Extended the `DocumentOut` schema in [schemas.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/backend/app/modules/files/schemas.py) to return `ocrUsed`, `ocrEngine`, and `vlmModel` dynamically.
* **Extraction Strategy Resolver**: Improved [service.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/backend/app/modules/files/service.py) to load and match the active template/document type strategy, resolving a bug where the remote `paddle_qwen` pipeline incorrectly fell back to the `rapidocr` badge.
* **Frontend Component Redesign**: Updated [page.tsx](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/frontend/app/(app)/documents/[id]/page.tsx) to split badges into:
  * **Source Modality**: *Digital Read* (Slate), *GPU OCR (Paddle)* (Indigo), or *Local OCR (Rapid)* (Cyan).
  * **Extraction Strategy**: *Deterministic Match* (Emerald), *VLM Extraction (Qwen-VL)* (Purple), or *Manually Verified* (Amber).

---

## 3. Nested Line Items & Sub-items Rendering
* **Recursive Hierarchy Renderer**: Replaced the flat `String(v)` interpolation in the document details card view with a recursive layout check. If an item property contains nested arrays (like `sub_items` list), it renders them nested and indented (`pl-3 border-l-2`) with customized keys/values at `text-[11px]`.
* **Input Field Hardening**: Hardened the correction form to filter out complex objects and array types, showing inputs only for flat primitives. This stops React controlled component warnings and prevents raw object serialization from corrupting data on save.

---

## 4. Research & Competitor Analysis (Outside IDE)
* **Paperless-ngx & Docling**: Evaluated document parsing architectures and bottleneck factors:
  * *Paperless-ngx*: Relies on Tesseract OCR (CPU-bound bottleneck, slower table/grid handling).
  * *Docling*: Optimized layout parsing via deep layouts, but demands higher GPU/VRAM resources.
* **SMB Use Cases & Extract Integration**:
  * Researched how Small/Medium Businesses can automate general ledger (GL) coding and invoice reconciliations using hierarchical line item extractions.
  * Formulated pipeline workflows for feeding the extracted JSON directly into accounting systems (like QuickBooks/Xero) or workflow systems via webhooks.
