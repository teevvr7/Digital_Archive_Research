# Daily Progress Report — 30 June 2026

## Overview
Implemented and verified dynamic JSON key sorting, schema-aware post-extraction validation checks, clock drift JWT tolerance, and route access gatekeeping. All backend tests (61/61) are passing.

---

## 1. Dynamic JSON Key Sorting
* **Backend Ordering**: Integrated recursive sorting logic into `_doc_to_out` inside [service.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/backend/app/modules/files/service.py).
* **Order Preservation**: Before returning a document payload, the backend fetches the custom template settings and recursively re-orders `extracted_data` to match the exact top-down custom key sequence. This overcomes PostgreSQL's `JSONB` automatic alphabetical sorting, allowing both the "Extracted Data" and "Raw JSON" tabs to display in the user's custom sequence.

---

## 2. Decoupled, Schema-Aware Validation
* **Decoupled Structure**: Modified `ensure_structure` and `validate_extraction` in [paddle_qwen.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/backend/app/modules/idp/paddle_qwen.py) to be schema-aware.
* **Math & Field Scans**: Replaced old hardcoded keys with recursive dictionary key-matching. Math and vendor verification checks now search custom layouts for keys matching sub-total, tax, and supplier name patterns, preventing empty key injections and false human-review triggers.

---

## 3. JWT Leeway & Auth Gatekeeper
* **Clock Skew Tolerance**: Appended `leeway=60` to the JWT decoding block in [security.py](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/backend/app/core/security.py) to resolve local-to-Supabase clock drift login failures (`The token is not yet valid (iat)`).
* **Layout Isolation**: Modified `<AuthProvider>` in [auth.tsx](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/frontend/lib/auth.tsx) to only render pages (`children`) if the user is authenticated. This secures private URLs from flashing or showing mock grids when unauthenticated users visit them during a login redirect.
