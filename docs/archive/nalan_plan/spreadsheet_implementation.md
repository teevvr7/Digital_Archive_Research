# Spreadsheet Center — Implementation Plan

## Goal

Add a dedicated **Spreadsheet Center** page (`/spreadsheet`) to the sidebar that lets users:
1. Filter documents by **document type**, **template**, **date range**, and **status**
2. See which **columns** are available based on their selection — dynamically
3. Pick which columns to include in the export
4. Preview the data in a table
5. Download the result as **CSV**

---

## Known Data Challenges (Addressed in This Plan)

| Problem | How This Plan Solves It |
|---|---|
| Inconsistent key names (`vendor` vs `vendor_name`) | Runtime **alias map** normalises keys before display/export |
| Mixed value types (`"$ 123.00"` string vs `123.0` float) | `parse_amount()` coerces currency strings to floats |
| Nested `lineItems` arrays | Two modes: **Summary** (1 row per doc) and **Expanded** (1 row per line item) |
| `camelCase` vs `snake_case` mix | Alias map canonicalises to `camelCase` |
| No canonical schema across doc types | Column discovery is scoped to the user's **selected doc type/template** filter |
| Arbitrary JSONB keys | Dynamic `jsonb_object_keys` query — no hardcoding |

---

## Architecture Overview

```
Frontend: /spreadsheet page
    │
    ├── GET /api/export/meta ──────────► Returns doc types + templates list
    │
    ├── POST /api/export/fields ───────► Given filters → returns available column keys
    │
    └── POST /api/export/spreadsheet ──► Given filters + columns + mode → returns CSV blob
                                          (also used for in-page preview as JSON)

Backend: new export module
    ├── router.py   (3 endpoints)
    ├── service.py  (query + flatten + normalise logic)
    └── normalise.py (alias map + parse_amount)
```

---

## Phase 1: Backend

### 1.1 New Module: `backend/app/modules/export/`

#### [NEW] `backend/app/modules/export/__init__.py`
Empty init.

#### [NEW] `backend/app/modules/export/normalise.py`

Two utilities, no external dependencies:

```python
FIELD_ALIASES = {
    # Vendor variations → canonical "vendor"
    "vendor_name": "vendor",
    "supplier": "vendor",
    "company_name": "vendor",
    # Invoice number
    "invoice_no": "invoiceNumber",
    "invoice_number": "invoiceNumber",
    "doc_number": "invoiceNumber",
    # Totals
    "grand_total": "totalAmount",
    "total_amount": "totalAmount",
    "total": "totalAmount",
    "amount_due": "totalAmount",
    # Dates
    "invoice_date": "invoiceDate",
    "date": "invoiceDate",
    "document_date": "invoiceDate",
    # Line items
    "line_items": "lineItems",
    # Sub-total
    "subtotal": "subtotal",
    "sub_total": "subtotal",
    "subtotal_amount": "subtotal",
    # Tax
    "tax_amount": "tax",
    "gst": "tax",
    "vat": "tax",
}

def normalise_keys(data: dict) -> dict:
    """Remap known aliases to canonical keys. Unknown keys pass through as-is."""
    ...

def parse_amount(val) -> float | None:
    """Coerce currency strings like '$ 1,200.50' to float."""
    ...
```

#### [NEW] `backend/app/modules/export/service.py`

Core logic — three functions:

**`get_export_meta(db, tenant_id)`** — returns available document types and templates for the filter dropdowns. Reuses existing `DocumentType` and `DocumentTemplate` models.

**`discover_fields(db, tenant_id, filters)`** — runs `jsonb_object_keys` scoped to the filtered documents, then applies the alias map to deduplicate. Returns a sorted list of canonical column names.

```python
def discover_fields(db, tenant_id, *, doc_type, template_id, status) -> list[str]:
    """Return distinct top-level keys in extracted_data for matching docs."""
    stmt = select(func.distinct(func.jsonb_object_keys(Document.extracted_data))).where(
        Document.tenant_id == tenant_id,
        Document.extracted_data.is_not(None),
        Document.deleted_at.is_(None),
    )
    if doc_type:
        stmt = stmt.where(Document.document_type == doc_type)
    if template_id:
        stmt = stmt.where(Document.template_id == template_id)
    if status:
        stmt = stmt.where(Document.status == status)

    raw_keys = db.scalars(stmt).all()
    # Normalise through alias map to deduplicate
    seen = set()
    canonical_keys = []
    for k in raw_keys:
        c = FIELD_ALIASES.get(k, k)
        if c not in seen:
            seen.add(c)
            canonical_keys.append(c)
    return sorted(canonical_keys)
```

**`build_spreadsheet(db, tenant_id, filters, columns, mode)`** — queries documents, normalises each `extracted_data`, flattens according to mode, returns `list[dict]`.

- **Summary mode**: 1 row per document. `lineItems` collapsed to count.
- **Expanded mode**: 1 row per line item. Document header fields repeat on each row.

#### [NEW] `backend/app/modules/export/router.py`

Three endpoints on `APIRouter(prefix="/export", tags=["export"])`:

| Method | Path | Purpose | Returns |
|---|---|---|---|
| `GET` | `/export/meta` | Doc types + templates for dropdowns | JSON |
| `POST` | `/export/fields` | Available columns for selected filters | JSON list of strings |
| `POST` | `/export/spreadsheet` | Preview OR download | JSON (`?format=preview`) or `text/csv` (`?format=csv`) |

The spreadsheet endpoint:
- `?format=preview` → returns `{ rows: [...], total: N }` for the preview table
- `?format=csv` → returns streaming CSV with `Content-Disposition: attachment; filename=export.csv`

#### [MODIFY] `backend/app/main.py`
Add: `app.include_router(export_router, prefix="/api")`

---

## Phase 2: Frontend

### 2.1 Sidebar Link

#### [MODIFY] `frontend/components/sidebar.tsx`

Add to `NAV_ITEMS` array (between Upload and Search):

```typescript
import { Table } from "lucide-react";
// in NAV_ITEMS:
{ href: "/spreadsheet", label: "Spreadsheet", icon: Table },
```

### 2.2 API Functions

#### [MODIFY] `frontend/lib/api.ts`

Add four new functions:
- `fetchExportMeta()` → `GET /export/meta`
- `fetchExportFields(filters)` → `POST /export/fields`
- `fetchExportPreview(filters, columns, mode)` → `POST /export/spreadsheet?format=preview`
- `downloadExportCsv(filters, columns, mode)` → `POST /export/spreadsheet?format=csv` → trigger browser file download from the returned blob

### 2.3 Spreadsheet Page

#### [NEW] `frontend/app/(app)/spreadsheet/page.tsx`

Layout — three sections top-to-bottom:

```
┌─────────────────────────────────────────────────────────────────┐
│ SPREADSHEET CENTER                                   [DL CSV]   │
├─────────────────────────────────────────────────────────────────┤
│ FILTERS BAR                                                     │
│ Type: [All ▾]  Template: [All ▾]  Status: [Completed ▾]       │
│ Date: [from] → [to]    View: ○ Summary  ● Expanded            │
├─────────────────────────────────────────────────────────────────┤
│ COLUMN PICKER (appears after type/template selected)            │
│ ☑ vendor   ☑ invoiceNumber   ☑ totalAmount   ☐ currency  ...  │
├─────────────────────────────────────────────────────────────────┤
│ PREVIEW TABLE                                                   │
│ vendor       │ invoiceNumber │ totalAmount │ ...                │
│ Acme Corp    │ INV-001       │ 500.00      │ ...                │
│ Odette's     │ INV-042       │ 250.00      │ ...                │
└─────────────────────────────────────────────────────────────────┘
```

**Behaviour flow (conflict-free dynamic selection):**

1. Page loads → `fetchExportMeta()` → populates Type and Template dropdowns
2. User selects a **document type** → templates dropdown filters to only matching templates → `fetchExportFields()` fires → column picker updates with only the keys that exist in the filtered data
3. User selects a specific **template** → type dropdown auto-locks to that template's type → columns re-fetch
4. On any filter change → columns re-fetch → preview re-fetch
5. Column checkboxes are **regenerated on every filter change** — impossible to select columns that don't exist for the current combination
6. Toggle Summary ↔ Expanded → in Expanded mode, extra pseudo-columns appear: `item_description`, `item_quantity`, `item_unitPrice`, `item_amount`
7. "Download CSV" → `downloadExportCsv()` → browser downloads file

---

## Phase 3: Line Item Flattening

### Summary Mode (default)
- 1 row per document
- `lineItems` excluded from column picker
- If user still wants item info, a count column `item_count` is available

### Expanded Mode
- 1 row per line item (document header fields repeat)
- Extra columns: `item_description`, `item_quantity`, `item_unitPrice`, `item_amount`
- Documents with no line items → still appear as 1 row
- Sub-items (`sub_items` nested inside line items) → flattened as additional rows with a `depth` column marker (0 = parent, 1 = sub-item)

---

## Files Summary

### Backend (4 new, 1 modified)

| Action | File |
|---|---|
| [NEW] | `backend/app/modules/export/__init__.py` |
| [NEW] | `backend/app/modules/export/normalise.py` |
| [NEW] | `backend/app/modules/export/service.py` |
| [NEW] | `backend/app/modules/export/router.py` |
| [MODIFY] | `backend/app/main.py` |

### Frontend (1 new, 2 modified)

| Action | File |
|---|---|
| [NEW] | `frontend/app/(app)/spreadsheet/page.tsx` |
| [MODIFY] | `frontend/components/sidebar.tsx` |
| [MODIFY] | `frontend/lib/api.ts` |

---

## What This Plan Does NOT Include (Deliberately)

- **No DB migration** — reads `extracted_data` JSONB at runtime
- **No XLSX format** — CSV first; add XLSX later with `openpyxl` if needed
- **No saved presets** — ship dynamic picker first
- **No materialised columns** — alias map handles normalisation at read time

---

## Verification Plan

### Manual Testing
1. Navigate to `/spreadsheet` — sidebar link and page loads
2. Select "invoice" type → column picker shows only invoice-relevant fields
3. Select a template → type auto-locks and columns update
4. Toggle Summary → Expanded → row count changes
5. "Download CSV" → file downloads with correct headers and data
6. Test with docs that have no `extracted_data` → excluded gracefully
7. Test with mixed deterministic + VLM docs → no duplicate columns after normalisation

### Automated
- Run existing test suite for regressions
- New unit tests for `normalise_keys()` and `parse_amount()`

---

## Post-Implementation Review & Refinements (Added 2026-07-10)

### 1. Theme Consistency (Light/White Mode)
* **Finding**: The page was built with a custom dark background (`bg-slate-900`, `bg-slate-800`), whereas the rest of the application uses a clean light/white theme (`bg-slate-50` background, `bg-white` panels, `border-slate-200` borders, `text-slate-900` text, and blue accent buttons).
* **Solution**: Refactor `frontend/app/(app)/spreadsheet/page.tsx` classes to align with the application styling:
  * Container background: `bg-slate-50`
  * Card panels: `bg-white border-slate-200 rounded-xl p-5 shadow-sm`
  * Typography: `text-slate-900` for headers, `text-slate-500` for secondary labels
  * Button / Accent color: `bg-blue-600 hover:bg-blue-700` instead of `bg-emerald-600`
  * Table styles: `bg-white border-slate-200 divide-y divide-slate-200`

### 2. Template / Filters Mapping Bug
* **Finding**: The template filter did not apply because `ExportFilters` and `SpreadsheetRequest` in `router.py` inherited from Pydantic `BaseModel` instead of `CamelModel`. This meant camelCase fields (`templateId`, `dateFrom`, `dateTo`) from the frontend were ignored or resolved as `None` on the backend.
* **Solution**: Refactor the request schemas in `router.py` to inherit from `CamelModel` and use standard Pythonic snake_case attributes:
  ```python
  class ExportFilters(CamelModel):
      document_type: str | None = None
      template_id: uuid.UUID | None = None
      status: str | None = None
      date_from: datetime.date | None = None
      date_to: datetime.date | None = None
  ```
  Pydantic + `CamelModel` will automatically deserialize incoming camelCase JSON fields and coerce strings directly to UUIDs and dates.

### 3. Dynamic Column Loading from Template / Type Schema
* **Finding**: The column picker was populated solely by querying top-level keys of `extracted_data` in existing database records matching the filter. If no documents matching the filters had been processed yet, the picker remained blank.
* **Solution**: Enhance `discover_fields` in `service.py` to:
  * Load defined fields from `DocumentTemplate.field_mappings` if a template is selected.
  * Load defined fields from `DocumentType.json_schema` (or its promoted template) if only a document type is selected.
  * Union these schema keys with the distinct keys found in the database. This guarantees the column list is visible and selectable immediately.

### 4. Nested Object Cells (`[object]`)
* **Finding**: Structured VLM extractions containing nested dictionary or array values (e.g. addresses, arrays, sub-items) were stringified as `[object Object]` in the UI and written as Python dict representations in CSV.
* **Solution**: 
  * **Frontend table**: Modify `formatCellValue` to check if `typeof val === "object"` and apply `JSON.stringify(val)` for clean formatting.
  * **Backend CSV**: Update CSV generation in `router.py` to check for `dict` or `list` types and write them using `json.dumps(val)` to output valid JSON string cells instead of raw python strings.

