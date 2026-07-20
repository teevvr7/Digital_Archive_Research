# 2026-07-16 — Predefined Custom Fields Per Document Type + Search/Filter Integration

**Branch:** `mvp-lvl2`
**Status at end of day:** All four pieces implemented, tested, and verified live. Not yet committed.

---

## Context

User's own suggestion, prompted by testing the existing (flat, tenant-wide) custom fields feature: custom fields should be **predefined per document type** rather than a single undifferentiated catalog shown on every document regardless of relevance, and the upload flow should prompt for the right fields at upload time instead of leaving metadata capture as an afterthought. Planned properly in plan mode before writing any code (per user's explicit "do proper planning" instruction), then iterated twice more the same day as live testing surfaced two further real gaps — each also planned before implementing.

---

## Piece 1 — Predefined custom fields per document type + upload-time popup

**Data model:** new table `document_type_fields` (migration `0015`) links an existing `custom_fields` catalog entry to one of the 7 fixed document-type strings (invoice/receipt/contract/report/letter/form/other) as "predefined" for that type, with a `required` flag and `position`. Deliberately keyed off the type **string**, not a `document_types.id` FK — that table's per-tenant/dynamic capability stays dormant (unused since the original schema) until tenant-defined types become a separate future feature; the user confirmed document types stay fixed for now. Migration also seeds sensible starter fields for every existing tenant (Invoice: PO Number/Payment Terms; Receipt: Expense Category; Contract: Contract End Date/Renewal Reminder; Report: Department) — fully editable/removable afterward.

**Backend:** `resolve_custom_field_type`/predefined-field CRUD in `modules/metadata/service.py` + 4 new router endpoints (`GET /document-type-fields`, `POST/PATCH/DELETE /document-types/{type}/fields`). Upload flow (`files/service.py::create_documents`) extended with two new optional per-file form fields — `field_values` (JSON `{field_id: value}`) and `new_fields` (JSON `[{name, fieldType, options, value}]` for ad-hoc fields created inline, auto-attached as predefined for that file's type going forward, per the user's confirmed design choice). Both threaded through the existing dedup/validation pipeline as parallel arrays, applied in a new `_apply_upload_time_fields` helper that is deliberately best-effort — any parse/validation failure is logged and skipped, never raised, so a bad field value can never block the document itself from archiving (CLAUDE.md's ingestion-never-blocks rule).

**Frontend:** new shared `components/custom-field-input.tsx` (extracted from the document detail page's inline type-switch logic) reused by the upload popup, the Custom Fields management page, and the detail page — one source of truth for how each field type renders. Custom Fields page gained a "Predefined fields by document type" section. Upload page gained an icon button (+ bulk-toolbar variant) opening a popup to fill predefined fields and define new ones inline before the file uploads. Document detail page's custom-fields section scoped down from "show the entire tenant catalog on every document" to "predefined-for-this-type ∪ already-has-a-value" — with the previously-dead `showFieldPicker` state wired up as a genuine "+ Add field" affordance so the ability to attach an arbitrary field manually isn't lost.

**Result:** 368/368 backend tests passing (19 new), `tsc`/`eslint` clean, verified live end-to-end.

---

## Piece 2 — Fix a same-session staleness gap + add "use an existing field"

Live testing surfaced two follow-ups, raised by the user and planned before touching code:

1. **Staleness:** the upload page's `predefinedFields` state was fetched once on mount and never refetched — creating a new field mid-session wouldn't show up as predefined for the *next* file added in the same session (only after a page reload). Fixed by refetching `apiPredefinedFields()` after every upload batch completes.
2. **Missing capability, the user's own correct fix:** the popup only offered "fill predefined fields" or "create a brand-new field" — no way to attach an *already-existing* catalog field (e.g. reuse Receipt's "Expense Category" on an Invoice) without leaving the upload page. Added a **"Use existing field"** button alongside "Create new field" in the popup, backed by a new `attach_fields` per-file form param (`[{fieldId, value}]`) — attaches the field as predefined for that type (tolerating a 409 "already attached" gracefully, still setting the value) and sets its value, deferred to actual upload submission (not eager on pick) so closing the popup without uploading never silently attaches anything.

**Result:** 374/374 backend tests passing (6 new, including the 409-tolerance case), `tsc`/`eslint` clean.

---

## Piece 3 — Custom field search/filter on the Documents page (type-gated)

Custom field values were write-only until this point — capturable at upload, visible on one document's detail page, but not searchable or filterable, directly against this product's own stated "retrieval is the headline feature" priority. User's own design for solving the "custom fields can be many" scaling problem, confirmed as the approach: **gate the filter behind the existing Type filter** — picking a type unlocks a field picker showing only that type's *predefined* fields (reusing `document_type_fields`, already built), never the whole tenant catalog at once.

**Backend:** `build_document_query` (shared by `/documents` and CSV/XLSX export) gained 6 new optional params (`custom_field_id`, `custom_field_value`, `custom_field_min/max`, `custom_field_date_from/to`). A new `resolve_custom_field_type` helper looks up the field's type server-side (never trust a client-supplied type — it decides exact-vs-partial matching). Comparison logic branches by type: select/boolean get exact equality (a blind ILIKE would let `"Travel"` match `"International Travel"`), text/number get partial ILIKE, number/date additionally support min/max and from/to ranges. JSONB values needed Postgres's `#>>'{}'` "as text" extraction before ILIKE/cast comparisons — `.astext` isn't available on a whole (un-indexed) JSONB column in SQLAlchemy, only verified this empirically against the live DB before writing the real code (a quick throwaway script confirmed the working syntax and caught a wrong-type test-parameter mistake along the way). Threaded through `/documents/export` identically, keeping the "export never drifts from the list filter" invariant.

**Frontend:** Documents page fetches `predefinedFields` alongside tags/correspondents; the picker (and its type-conditional value control — single input or select for text/select/boolean, min/max or from/to range for number/date) only renders once a Type is selected and that type has predefined fields. Resets whenever Type changes. Wired into saved views.

**Tests:** new `test_custom_field_documents_filter.py`, live-Postgres integration tests (same pattern as `test_search_service.py`) — needed real JSONB cast behavior verified, not mocks. Deliberately seeded a substring-collision pair ("Travel" / "International Travel") specifically to catch the over-match risk the exact-match branch exists to prevent.

**Result:** 381/381 backend tests passing (7 new), `tsc`/`eslint` clean, verified live.

---

## Piece 4 — Two UX refinements from live feedback

1. **Removed the Amount (Min RM → Max RM) and Vendor filters from the Documents page** — user flagged them as unnecessary clutter now that custom fields cover similar ground. Removed the frontend state, `buildQuery`/saved-view wiring, and the input controls; deliberately left the backend capability (`amount_min`/`amount_max`/`vendor` in `build_document_query`, `list_documents`, export) untouched — still legitimate underlying data (shown on the detail page, still a CSV export column), still tested, just no longer surfaced as a Documents-page filter control. Frontend-only change; backend test suite unaffected.
2. **Number-field filter defaults to "Contains," not "Range."** User's real complaint: a field like "Order Number" is an identifier people search by a few remembered digits, not a quantity you'd bound with min/max — the range UI made it hard to find a document without already knowing the exact number. Added a small Contains/Range toggle for number-type fields (Contains is the default); the backend's number branch was extended to accept a partial ILIKE match via `custom_field_value` (in addition to the existing min/max range), so both modes ride the same query-building code path with no schema change.

**Result:** 382/382 backend tests passing (1 new — the number-field Contains case), `tsc`/`eslint` clean.

---

## Overall result

- Backend test suite grew through the day: 368 → 374 → 381 → **382/382 at completion**, zero regressions at any step.
- `tsc --noEmit`: clean throughout (same 2 pre-existing, unrelated `search/page.tsx` errors, confirmed untouched by every diff this session).
- `eslint`: the one recurring warning (`react-hooks/set-state-in-effect` on the Documents page's existing `refreshDocuments()` effect) confirmed pre-existing via `git diff` before being left alone, each time it reappeared after further edits to the same file.
- Every backend change re-verified against the live Postgres DB (not just mocks) before being called done — including a from-scratch empirical check of the exact SQLAlchemy JSONB "as text" extraction syntax, since getting that silently wrong would have broken every non-trivial custom-field filter.
- Two live plan-mode sessions beyond the first (Pieces 2 and 3) were entered specifically because the user asked "give your point of view and plan it properly" each time real usage surfaced a further gap — not designed speculatively upfront.

## Next

Not yet committed — pending user testing of today's full set of changes (predefined fields, the two upload-popup follow-ups, the type-gated filter, and the two UX refinements) before deciding what to bundle into a commit.
