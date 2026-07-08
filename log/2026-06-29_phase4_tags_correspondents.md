# Phase 4 — Organization: Tags + Correspondents
**Date:** 2026-06-29  
**Branch:** `mvp-lvl2`  
**Prior state:** Phase 3 complete (121/121 tests, migration 0008 live, soft-delete/trash/PATCH endpoints done)

---

## What was built

### Migration
- `backend/app/migrations/versions/0009_tags_correspondents.py`
  - New tables: `tags`, `document_tags`, `correspondents`
  - All with `tenant_id` NOT NULL + RLS (`ENABLE`, `FORCE`, NULLIF GUC policy, `GRANT` to `authenticated`)
  - `UNIQUE(tenant_id, name)` on both `tags` and `correspondents`
  - Added `correspondent_id UUID REFERENCES correspondents(id) ON DELETE SET NULL` to `documents`

### Backend — new files
| File | Purpose |
|---|---|
| `app/models/tag.py` | `Tag` + `DocumentTag` ORM models; ALGO_* constants |
| `app/models/correspondent.py` | `Correspondent` ORM model |
| `app/modules/tags/matching.py` | Deterministic match engine (none/any/all/literal/regex); `run_document_matching()` |
| `app/modules/tags/schemas.py` | `TagIn`, `TagPatchIn`, `TagOut` (CamelModel) |
| `app/modules/tags/service.py` | Tag CRUD + `assign_tag` (ON CONFLICT DO NOTHING) + `unassign_tag` |
| `app/modules/tags/router.py` | GET/POST /tags, PATCH/DELETE /tags/{id}, POST/DELETE /documents/{id}/tags/{tag_id} |
| `app/modules/correspondents/schemas.py` | `CorrespondentIn`, `CorrespondentPatchIn`, `CorrespondentOut` |
| `app/modules/correspondents/service.py` | Correspondent CRUD |
| `app/modules/correspondents/router.py` | GET/POST /correspondents, PATCH/DELETE /correspondents/{id} |
| `app/tests/test_tags.py` | ~35 tests: matching algorithms, CRUD, auto-matching |
| `app/tests/test_correspondents.py` | ~10 tests: CRUD + auto-link |

### Backend — modified files
| File | Change |
|---|---|
| `app/models/__init__.py` | Added Tag, DocumentTag, Correspondent imports + `__all__` |
| `app/models/document.py` | Added `correspondent_id` FK column |
| `app/modules/files/schemas.py` | `TagOut`/`CorrespondentOut` added; `DocumentOut.tags` → `list[TagOut]`; `DocumentOut.correspondent` added |
| `app/modules/files/service.py` | `_fetch_tags_for_docs`, `_fetch_correspondents_for_ids` batch helpers; `list_documents` tag_id filter; `_doc_to_out` updated |
| `app/modules/files/router.py` | Added `tag_id` query param to list endpoint |
| `app/modules/idp/jobs.py` | `run_document_matching()` called after `STATUS_COMPLETED`, crash-isolated |
| `app/main.py` | Registered tags + correspondents routers |
| `app/tests/test_enqueue_on_upload.py` | Added `correspondent=None` to `DocumentOut` in test helper |
| `app/tests/test_file_management.py` | Added `doc.correspondent_id = None` to `_make_doc()` |

### Frontend — new files
| File | Purpose |
|---|---|
| `app/(app)/tags/page.tsx` | Full CRUD: table + modal (color picker, match rules, inbox flag) |
| `app/(app)/correspondents/page.tsx` | Full CRUD: table + modal (name, match, algorithm, case-insensitive) |

### Frontend — modified files
| File | Change |
|---|---|
| `types/index.ts` | Added `Tag`, `Correspondent` interfaces; updated `Document` |
| `lib/api.ts` | Tag + correspondent CRUD + assign/unassign API functions |
| `lib/mock-data.ts` | All 8 mock docs: `tags: [], correspondent: null` |
| `app/(app)/documents/page.tsx` | Tag filter dropdown, colored tag chips |
| `app/(app)/documents/[id]/page.tsx` | Inline tag assign/unassign, correspondent in Metadata tab |
| `components/sidebar.tsx` | "Organize" nav section with Tags + Correspondents links |

---

## Key design decisions

- **Matching engine is 100% deterministic** — no ML, no GPU. Algorithms: none/any/all/literal/regex evaluated against `title + extracted_text` (capped at 5000 chars). Per "heuristic rules first" directive.
- **Idempotent tag assignment** — `INSERT ... ON CONFLICT (document_id, tag_id) DO NOTHING` makes auto-matching safe to retry.
- **Crash isolation** — auto-matching in `jobs.py` is wrapped in try/except; a matching failure never blocks document completion (same pattern as thumbnail generation).
- **No N+1 queries** — batch helpers load all tags/correspondents for a full page of documents in 2 queries, not N queries.
- **Correspondent first-match wins** — only the first matching correspondent is linked per document; vendor name from `extracted_data` is also checked (case-insensitive equality).

---

## Test results
- **154/161 tests passing** before migration applied
- **7 failing tests** are DB integration tests (`test_search_service.py`, `test_idp_tenant_isolation.py`, `test_search_tenant_isolation.py`) — they fail because `correspondent_id` column doesn't exist yet in DB
- All 7 will pass after `alembic upgrade head`

---

## Manual steps required

1. **Apply migration:**
   ```bash
   cd backend
   python -m alembic upgrade head
   ```

2. **Verify tests:**
   ```bash
   pytest
   # Expected: 161/161 passing
   ```

3. **Smoke test UI** (backend on :8001, frontend running):
   - `/tags` → create a tag with auto-match rule → upload a doc → verify auto-assigned
   - `/correspondents` → create a correspondent with match rule → verify auto-linked
   - Documents list → tag filter dropdown works
   - Document detail → tag add/remove inline + correspondent shown

---

## Next phase
**Phase 5 — Metadata:** custom-field catalog + typed values (JSONB hybrid) + correction UI for extracted fields.
