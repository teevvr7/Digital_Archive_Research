# 2026-07-10 — Level 3 (Data Value) Implementation

**Branch:** `mvp3-prod`
**Status at end of day:** All 6 Level 3 features implemented and verified live. Not yet committed — pending user testing.

---

## Context

Continuation of the production level-up roadmap (see `log/2026-07-09_production_levelup_l1.md` for Level 1 and the full plan). Asked which level to do next — Level 2 (IDP pipeline port) needs a Lightning AI GPU endpoint the user hasn't deployed yet, so user chose **Level 3 (Data value) first**, since it has no external dependency.

Before implementation, re-entered plan mode and ran a targeted Explore pass to get exact current-state facts (migration head, `Document` model columns, both live extraction JSON schemas side by side, current filter code, signed-URL helpers, bulk-operation patterns, RLS conventions) rather than relying on the earlier audit from a day prior, since several files had since changed. This surfaced an important scoping correction: the original plan bullet said "reuse the Level-2 canonical schema" for typed columns, but the user picked L3 before L2 — so L3 had to build its own lightweight two-schema mapper (`idp/normalize.py`) instead, designed so L2 can extend it with a third branch later rather than redoing it.

One design decision required explicit sign-off before writing any code: the shareable-links feature needs a public, unauthenticated endpoint that deliberately bypasses RLS (the token itself is the authorization, not a JWT — same precedent as `auth/service.py::bootstrap`). Per CLAUDE.md's "never bypass tenant isolation without asking" rule, this was raised via AskUserQuestion before implementation. **User approved the token-gated public-link approach.**

---

## Infra note before starting: backend/worker background-process instability

At the start of this session, the entire `D:` drive (where the whole project lives — confirmed via PowerShell to be a Seagate "One Touch" **external USB drive**, not internal) disconnected at the OS level for about a minute, killing all three running dev services simultaneously. It reconnected on its own; `git status`/`git fsck` confirmed the repo was fully intact, no data lost. Flagged to the user directly: this is a real risk (a mid-write disconnect could corrupt data, not just crash a process), Windows reported `HealthStatus: Warning` on the volume. User's call: keeping the project on `D:` for now.

Separately (unrelated to the drive), backend+worker background processes kept dying shortly after clean restarts — happened 3 times in a row, while the frontend (started via `npm run dev`) stayed up throughout. Switched from Bash-tool-tracked background jobs to PowerShell `Start-Process` (fully detached OS processes, redirected to log files) for backend/worker, which resolved it for the rest of the session.

---

## Level 3 implementation — six pieces, all shipped

**1. Typed extraction columns.** Migration `0012_extraction_typed_fields.py`: added `vendor`, `invoice_no`, `total_amount NUMERIC(12,2)`, `currency`, `duplicate_of_document_id` to `documents`, plus `(tenant_id, total_amount)` and `(tenant_id, vendor)` indexes. New `idp/normalize.py::extract_typed_fields()` reads both live extraction schemas — deterministic tier's camelCase (`vendor`/`invoiceNumber`/`totalAmount`) and the VLM tier's snake_case (`vendor`/`invoice_number`/`total_amount`/`grand_total`) — confirmed by reading both `extract.py` and `extraction.py` directly rather than assuming. Backfill for existing rows done as a **Python loop inside the migration, not a raw SQL `::numeric` cast** — VLM output is LLM-sourced and occasionally non-conforming (e.g. `"1,234.50"`), and a single bad value would abort a raw-SQL migration transaction outright. Wired into `idp/jobs.py` at all three places `extracted_data` gets written (deterministic accept, VLM accept in `process_document`, VLM accept in `ai_extract_document`) so future documents stay in sync, not just the one-time backfill.

First migration attempt failed with `CompileError: Unconsumed column names` — the `sa.table()` reflection used for the backfill only declared `id`/`extracted_data` columns, not the four new ones being written to. Postgres transactional DDL meant the failed attempt rolled back cleanly (confirmed via `alembic current` still showing `0011`); fixed by declaring all four columns in the `sa.table()` call, re-ran successfully.

**2. Amount & vendor filters.** `files/service.py`'s WHERE-clause builder (previously the private `_build_document_query`, inlined in `list_documents`) was extracted and promoted to a public `build_document_query()` so the new export feature (item 3) could reuse it without duplicating filter logic — the two must never drift on what counts as "matching the current filters." Added `amount_min`/`amount_max`/`vendor` params end to end (service → router → frontend query type → Documents page filter bar, three new inputs after the date range).

**3. CSV / XLSX export + zip bulk-download.** New `modules/export/` module. `openpyxl` was worker-only in `pyproject.toml` (would `ImportError` in the lean API image) — promoted to base dependencies since it's pure Python with no native deps, safe to widen. `GET /documents/export?format=csv|xlsx` reuses `build_document_query`, capped at 5,000 rows — flagged via an `X-Export-Truncated` response header rather than silently dropping rows (required adding `expose_headers` to the CORS config so frontend JS can actually read it, since the export needs to be fetched with an auth header, not a plain `<a href>`). `POST /documents/bulk-download` zips selected originals in-memory, capped at 100 files (synchronous in the request handler — a real, documented limit, not hidden). Frontend: Export dropdown (CSV/Excel) and a Download button in the Documents page bulk-action bar, using a new `downloadFile()` helper that fetches with the auth header and triggers a browser save via a temporary `<a>` + `URL.createObjectURL`.

**4. Retroactive rule backfill.** New `POST /tags/apply-rules`, running the existing (already-built, previously never-backfilled) `run_document_matching` engine over already-ingested documents. **Caught a real design bug before writing any code**: a naive "just LIMIT 200 per call" version would have re-processed the same newest 200 documents on every call forever, since — unlike `extract_missing`, which naturally shrinks its own candidate set via `WHERE extracted_data IS NULL` — there's no column that marks "already rule-matched." Fixed by paginating oldest-first (`ORDER BY uploaded_at ASC`, `page` param, `hasMore` in the response) so repeated calls actually walk the whole tenant. "Apply rules to existing documents" button added to the Tags page, loops calling with incrementing page until done.

**5. Shareable links.** New `document_shares` table (migration `0013`, standard RLS pattern) + `modules/shares/`: authenticated `create`/`list`/`revoke` (normal tenant-scoped session) plus one deliberately public `GET /api/share/{token}` (raw `SessionLocal()`, no RLS — the unguessable `secrets.token_urlsafe(32)` token is the authorization, approved by the user before implementation per the note above). Expiry capped 1–30 days. New "Share" button + modal on the document detail page (create link, copy, revoke, see existing links), and a new public frontend route `frontend/app/shared/[token]/page.tsx` (outside the authenticated route group, same shape as the `reset-password` page) that resolves the token and offers a download.

**6. Auto-title + duplicate detection.** Both live in `idp/jobs.py::process_document` only — explicitly never on manual re-extraction (`ai_extract_document`), so a title the pipeline or the user already set can never get clobbered by a later re-run. When both vendor and invoice number are present after a successful extraction: title is set to `"{vendor} — {invoiceNo}"`, and a query checks for another non-trashed document in the tenant with the same vendor+invoice number. A match sets the new `duplicate_of_document_id` column and writes an `ACT_DUPLICATE_DETECTED` activity event — both purely advisory, never blocking (a resubmitted/corrected invoice must still archive normally, per CLAUDE.md's ingestion-never-blocks rule).

Adding `duplicate_of_document_id` to the `DocumentOut` API response schema (needed for the frontend badge) broke 12 existing tests: their `MagicMock(spec=Document)` fixtures didn't set the new attribute, and an unconfigured attribute on a spec'd MagicMock auto-vivifies as a child MagicMock rather than `None` — which failed Pydantic's UUID validation. Same failure class as previous sessions' `.title`/`db.execute().first()` gotchas. Fixed by adding `doc.duplicate_of_document_id = None` to the two affected fixture helpers (`test_file_management.py`, `test_custom_fields.py`).

---

## Result

- Backend test suite grew feature-by-feature: 255 (after typed columns) → 266 (export) → 272 (rule backfill) → 288 (shares) → **295/295 at completion** (auto-title/duplicates), zero regressions at any step.
- `tsc --noEmit`: clean throughout (same 2 pre-existing unrelated `search/page.tsx` errors, untouched).
- `eslint`: every new violation checked against the file's pre-change baseline; all were either pre-existing lines untouched by this session's edits, or matched the codebase's already-established tolerance for the `react-hooks/set-state-in-effect` pattern (present in `documents/page.tsx`, `tags/page.tsx`, etc. before this session).
- Every new/changed backend route re-verified live after each restart using the project's standard 401-not-404 check (no `--reload` used, per the known uvicorn-stale-serving gotcha).
- Two migrations applied live: `0012_extraction_typed_fields`, `0013_document_shares`.

## Next

Level 2 (port the newer IDP pipeline from `origin/main`, normalize the extraction JSON into one canonical shape) is next per the roadmap — blocked on the user deploying a PaddleOCR-VL endpoint on their Lightning AI GPU studio. This will also be the point where `idp/normalize.py` gains a third branch for `paddle_qwen`'s nested schema, and where the currently-orphaned `document_types`/`document_templates` tables get a real purpose via the ported IDP Control Center.
