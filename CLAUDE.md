# CLAUDE.md

> Context file for AI coding assistants. Read this before writing or modifying any code.

## 1. Project Overview

A multi-tenant, SaaS-based AI-supported **digital archive system** with an **Intelligent Document Processing (IDP)** module.

**North star:** a **general-purpose archive for ALL kinds of files** — PDF, scanned PDF, images, AND office formats (DOCX/XLSX/PPTX/TXT/CSV/email). The system **ingests anything → processes it (text + thumbnail + metadata for every file) → organizes it neatly → lets users retrieve any file fast and accurately.** **Retrieval is the headline feature** — if a user can't find a file in seconds, nothing else matters.

**Structured data extraction (invoices, receipts, …) is a cost-saving enhancement layered on top — NOT the point.** Invoices are simply the first document *type* to get deterministic structured extraction; every other file type still gets full ingestion, text, thumbnail, generic metadata, and search. A file is never blocked from being archived just because structured extraction doesn't apply to it.

**Primary goal:** a cost-efficient archive where the AI layer (~10–15% of logic) enriches a solid traditional-SaaS core (~85–90%). Deployed for Malaysia (PDPA-aware). **Cost-efficiency in storage and AI processing is the #1 priority in every decision.** Target: production-grade, not MVP-grade.

## 2. Tech Stack & Architecture

**Architecture:** Modular monolith + a single async worker. **NOT microservices.** Two logical tracks share one codebase: the SaaS core (API) and the IDP pipeline (worker).

**Backend**
- Python 3.11+ / **FastAPI**
- **PostgreSQL** (via Supabase) with **Row-Level Security (RLS)** for pooled multi-tenancy
- SQLAlchemy (ORM) + **Alembic** (migrations)
- **Redis + RQ** (or Celery) for the async IDP queue
- Auth via **Supabase Auth** (JWT)

**Storage**
- S3-compatible **object storage** (Supabase Storage / Cloudflare R2), encrypted at rest
- Files live in object storage **only**. The DB stores metadata + extracted JSON (`JSONB`). Never store file bytes in the DB.

**Search & retrieval — the headline feature** (no external search cluster; target <2s)
- `tsvector` full-text search over extracted text + filename (+ extracted field values)
- `pg_trgm` for fuzzy/typo filename matching; prefix tsquery for partial words
- `JSONB` + GIN indexes for long-tail metadata filtering
- Structured filters on typed fields: tag, correspondent/sender, document type, **document_date range, amount range**, custom fields
- **Saved views** (filter-rule sets + sort + display config) + facet counts, paperless-style

**IDP pipeline (worker) — deterministic-first cost cascade.** Each tier runs only when the cheaper one fails the quality gate:
- **Tier 0 — Parsing (free):** **PyMuPDF** text-layer extraction (skips OCR when a text layer exists — biggest cost saver) + page rasterization to PNG. A small **parser registry** routes by MIME (magic bytes, not extension): office → `python-docx`/`openpyxl`/`python-pptx`; text/csv/md → direct; email → headers+body. Multi-page → page-indexed block IR `{page, text, conf}`.
- **Tier 1 — OCR (cheap, CPU):** OpenCV preprocess → **RapidOCR** (`rapidocr-onnxruntime`, pip-only, CPU-only, Windows-friendly) with per-word confidence. Runs only when no usable text layer exists.
- **Tier 2 — Deterministic extraction (the core, CPU, ~$0):** `idp/extract.py` — keyword-gated templates (invoice2data engine, rules in `document_templates.field_mappings`) + `dateparser` + spaCy NER + regex/validators (amounts, invoice #, IBAN mod-97). `idp/gate.py` scores the candidate (completeness, format validity, OCR confidence, math-audit); **score ≥ 0.75 → `parsed_deterministic`**, else fall through.
- **Tier 3 — Layout/table models (CPU, behind the gate, feature-flagged):** docling TableFormer / TATR / PP-Structure / LiLT for hard tables & KIE. **MIT/Apache weights only** (see §6 licensing rule).
- **Tier 4 — VLM fallback (GPU/network, the exception handler, target 10–20% of docs):** **vLLM on Lightning AI Studio** (OpenAI-compatible, Qwen-VL class), outputs JSON. **The current VLM is a demo placeholder** — wired only as the gate-fail fallback seam; quality is enhanced later as separate work. Re-gate its output; still failing → `needs_review`.
- **⚠️ Dual-strategy update (Tev-Nal merge, 2026-07-29 — deliberate decision, not scope creep):** the deterministic-first cascade above is no longer the *only* path. `document_types.extraction_method` / `document_templates.extraction_method` now select **per document type/template**, resolved in `idp/pipeline.py::run_ai_extraction`, between `"cascade"` (Tiers 0–4 above, unchanged, including the Tier 4 demo-placeholder VLM) and `"paddle_qwen"` (a real remote two-stage engine — PaddleOCR-VL layout OCR → Qwen LLM structuring, `idp/paddle_qwen.py`, served from user-managed Lightning AI infra — bypasses Tiers 0–4 entirely and skips straight to structured JSON). **`paddle_qwen` is the default for newly-created document types** (via Settings → IDP Control Center); existing/legacy types keep resolving through `"cascade"` (migration-set `server_default`). This was an explicit user instruction overriding the Prime Directive below for this one architectural axis — the local deterministic pipeline was judged "just a demo" and paddle_qwen is now the primary intended engine, with cascade retained as the always-available, zero-network alternate strategy (still fully selectable per type/template, and still what carries typed-field extraction, auto-title/dedup, budget metering, and UBL/MyInvois XML parsing — re-integrated onto the `paddle_qwen` path too, see `backend/app/modules/idp/jobs.py`). Both strategies write through the same `Extraction` audit trail; only cascade's Tier 2 output passes through `gate.py`'s 0.75 score.
- Doc types are **dynamic** — stored as DB data, never hardcoded.
- **Self-learning loop:** `document_types` + `document_templates` capture learned layouts; `extractions` records every attempt (`method` = deterministic|vlm|manual) — powers the exception queue (low-confidence/`needs_review`) and promote-after-N. Every correction becomes a new rule → shrinks future VLM share.

**Frontend**
- **Next.js / React** + TypeScript, **shadcn/ui** component kit. Keep UI minimal.

**Ops:** Single region (Malaysia or Singapore). Sentry for error tracking.

**Key patterns**
- Async-first: uploads return instantly; all heavy IDP work runs in the worker, never in request handlers.
- Pooled multi-tenancy via RLS — `tenant_id` on every tenant-owned row, enforced at the DB.
- IDP cost cascade (now being built — see §2 IDP tiers): triage → parse → cheap deterministic extract → **quality gate (0.75)** → VLM only on gate-fail → store/index. The GPU runs only on the hard 10–20%.

## 3. Core Features

- Authentication & login (basic admin/user roles)
- Multi-tenancy via Postgres RLS (`tenant_id` everywhere, **DB-enforced** isolation — non-bypassrls role)
- File upload: **all file types** — PDF, scanned PDF, images, DOCX/XLSX/PPTX, TXT/CSV/MD, email
- Secure object storage + metadata records + **sha256 dedup**
- Async processing pipeline (queue + worker) with retry/backoff, never blocks on the VLM
- Universal processing: text extraction (text-layer + OCR), **thumbnail**, generic metadata (dates/entities/title) for every file
- Deterministic structured extraction behind a quality gate; VLM fallback only on gate-fail
- Organization: **tags** (color/hierarchy/auto-match), **correspondents/senders**, **typed custom fields**, **trash/soft-delete**
- Search & retrieval: fuzzy filename, full-text content, structured metadata filters, **saved views**, facet counts (<2s)
- Metadata correction UI (edit extracted fields → feeds self-learning)
- Bulk operations (multi-select tag / set type / delete / download)
- Document viewer (multi-format) + original download
- Web UI (upload, list with grid/table + thumbnails, search/filter, view, manage)

## 4. Roadmap & Current Phase

| Sprint | Weeks | Theme | Deliverable |
|---|---|---|---|
| 0 | 1 | Foundations | Walking skeleton: login works, RLS schema live, OCR+VLM spike on 1 doc |
| 1 | 2–3 | Core SaaS & ingestion | Upload → store → list → download; tenant isolation proven by test |
| 2 | 4–5 | Extraction pipeline | Async text extraction (text-layer + OCR), text stored & indexed |
| 3 | 6–7 | Search + structured IDP | Search <2s; supported doc types return correct JSON |
| 4 | 8 | Hardening & security | All journeys pass; RLS isolation tests green; no critical bugs |
| 5 | 9 | Pilot & launch | Pilot client live on real docs; KPIs instrumented |

**Milestones A–E ✅ complete** (auth, ingestion+RLS, IDP pipeline, search, VLM extraction). See git history + memory for details. The VLM stage shipped but is a **demo placeholder**.

**Phases 0–6 (production-grade DMS upgrade, paperless-ngx-inspired) ✅ complete** — production hardening (non-bypassrls `app_user` role, Sentry, LLM budget gate, storage quota), universal ingestion, deterministic extraction + gate + eval/corpus, file management/viewer/trash, tags/correspondents, custom fields, saved views/bulk ops/retrieval UX. Reference DMS at `../paperless`; extraction engines at `../invoice2data-master`, `../TemplatePro_2`, `../docling-main`.

**➡️ CURRENT WORK: Production Level-Up Roadmap** (full detail: `~/.claude/plans/compiled-moseying-tulip.md`) — closing the gaps between "working demo" and "buyable product," on branch `mvp3-prod`:

| Level | Theme | Status |
|---|---|---|
| 1 | Trust & credibility — real Settings/org profile, Sentry wired, rate limiting, audit trail, forgot-password | ✅ done, committed (`38b3341`) |
| 2 | IDP pipeline upgrade — `paddle_qwen` remote-HTTP engine as a **top-level default strategy** (not gate-fail-only, revised from the original plan — see dual-strategy note in §2), canonical `extracted_data` schema, IDP Control Center | ✅ code merged in `Tev-Nal` (2026-07-29, via teammate's `dev` branch); ⏸ still needs the user's live Lightning AI endpoint deployed + license check before extraction quality can be verified end-to-end |
| 3 | Data value — typed extraction columns (`vendor`/`invoice_no`/`total_amount`/`currency`), amount/vendor filters, CSV/XLSX/zip export, retroactive rule backfill, shareable links (token-gated public endpoint), auto-title + duplicate-invoice detection | ✅ done, committed (`6a013d6`) |
| 4 | Team accounts — invite-by-email (Supabase Auth admin), enforced admin/member roles beyond the existing `require_admin`, real multi-row Users tab replacing the single-user Settings view | ✅ done, committed (`b4f1300`) |
| 5 | SME growth & differentiators — **5 of 7 shipped**: onboarding starter kit, PWA/camera capture, email-sender→correspondent linking, MyInvois UBL-XML ingestion, trash auto-retention. Email-in ingestion and Malay FTS config **dropped by user request (2026-07-27)** — not being built | ✅ done (scope reduced) |

**Done (2026-07-27): full feature QA + bugfix pass** — every user-facing feature except the IDP pipeline internals was manually re-tested (real browser, screenshots reviewed) against a fresh throwaway tenant, with 9 functional bugs and UX issues found and fixed, incl. CSV/XLSX export being 100% broken via the UI (a router-registration-order bug the existing test suite never caught). Log: `log/2026-07-27_full_feature_qa_pass.md`.

**Done (2026-07-29): `Tev-Nal` branch — merged `mvp3-prod` (this line of work) with a teammate's `dev` branch.** Brought in: the real `paddle_qwen` remote extraction engine + IDP Control Center admin UI (see dual-strategy note in §2 above), Spreadsheet Center (`/spreadsheet`, `export/normalise.py`) added *alongside* the existing CSV/XLSX/zip export (both kept, not a replacement), `reprocess_document`, dynamic modality/source badges on the document detail page, JWT clock-skew leeway, and an unintegrated standalone RAG-chatbot prototype (`rag_dev/` — own DB/deps, not wired into the product, do not treat as shipped). Migrations `eebe53429cbf`/`62a974d876f0`/`2f0fd6e40db5` renumbered to `0017`–`0019` for convention and rebased onto `0016`. dev's cascade reimplementation had regressed UBL/MyInvois parsing, typed-field columns, auto-title/dedup, trash-retention, and budget metering — all re-integrated onto both strategies in `jobs.py`. Verified: 414/414 backend tests, 0 tsc/eslint errors, full migration chain applies clean, `next build` succeeds on all 19 routes, live health check OK. Not verified: real paddle_qwen extraction quality (no live Lightning AI endpoint in this session — needs the user's deployed endpoint to test end-to-end).

**Decisions locked:**
- Infrastructure: Supabase (DB + Auth + Storage), Redis + RQ (queue), vLLM on Lightning AI Studio
- Doc types: dynamic (DB data, not code); self-learning IDP pipeline
- JWT: HS256 verified with project secret; ES256/RS256 JWKS-based verification also supported
- OCR engine: **RapidOCR** (`rapidocr-onnxruntime`); PyMuPDF for parsing (LiteParse dropped — Rust beta, unstable on Windows)
- **Deterministic-first (cascade strategy only, as of the Tev-Nal merge):** within the `"cascade"` extraction strategy, the VLM runs ONLY after `gate.py` fails (score < 0.75) — unchanged. The `"paddle_qwen"` strategy (now the default for new document types, see §2) intentionally bypasses this gate entirely by design; changing the 0.75 threshold itself still needs human sign-off.
- **SaaS-friendly model licensing:** any ML/layout/table/OCR model weights must be **MIT or Apache-2.0**. Banned: YOLOv10 (AGPL), LayoutLMv3/LayoutXLM (CC BY-NC, non-commercial). Approved substitutes: TATR, LiLT, PaddleOCR/PP-Structure, docling/TableFormer, Donut, img2table, RapidOCR/Tesseract. Surya = defer (restricted weights).
- **Shareable links (Level 3):** one deliberate, narrow RLS exception — `GET /api/share/{token}` is public/unauthenticated, using a raw `SessionLocal()` session (same precedent as `auth/service.py::bootstrap`). The unguessable `secrets.token_urlsafe(32)` token is the authorization instead of a JWT. Approved by the user before implementation; expiry capped 1–30 days.
- **Team accounts (Level 4):** invites use Supabase Auth's admin `invite_user_by_email` (its own templated email — no SMTP infra added), followed by `admin.update_user_by_id(app_metadata={tenant_id, role})` so the accepted session's JWT carries the right tenant/role immediately, mirroring the existing `bootstrap()` pattern. The local `users` row is created at invite time (not deferred to first login) so admins can see pending invites; `last_login_at IS NULL` is the "pending" signal — no new status column. `email` stays globally unique (matches Supabase Auth's global-per-project identity); inviting an email that already has an account anywhere is rejected, not merged.
- **MyInvois/UBL-XML (Level 5):** `idp/ubl_invoice.py` parses UBL 2.1 Invoice XML directly into `ExtractionCandidate` — bypasses `extract.py`'s regex entirely (the XML is already structured) but still goes through the same `gate.score_extraction()`/accept path as every other deterministic source; `ocr_confidence=None` scores as a clean 1.0, same existing behavior text-layer PDFs already rely on. Never falls back to the VLM on gate-fail (no page image to send) — routes straight to `needs_review` instead, so a malformed e-invoice can't burn an LLM call. Uses stdlib `xml.etree.ElementTree` (no new dependency); rejects any XML declaring a DOCTYPE/ENTITY before parsing (cheap, deliberate XXE guard — legitimate UBL invoices never declare one). Real MyInvois-specific LHDN extensions (validation UUID/QR) aren't read yet — first slice targets standard UBL 2.1 only.

**Now approved (previously out-of-scope — built in the phases above):** deterministic extraction path, ML auto-classification, type-promotion / template-field management UI, exception-review/correction UI, structured metadata filtering, bulk ops, trash, data export (CSV/XLSX/zip), shareable public links, multi-user team accounts with roles.

**Still out of scope (do NOT build without explicit approval):** cold-tiering, analytics dashboards, public API beyond API-key auth, microservices, Elasticsearch/external search cluster, multi-region, SSO/SAML, mobile app, cross-encoder reranking. (pgvector semantic search is a later, optional Tier-3 item.)

## 5. Project Structure

```
/
├── CLAUDE.md
├── README.md
├── docker-compose.yml          # postgres, redis, backend, worker, frontend
├── .env.example
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI app entry
│   │   ├── worker.py           # RQ/Celery worker entry
│   │   ├── core/               # config, db session, security, TENANT/RLS context
│   │   ├── modules/            # feature modules (clear boundaries, no internal cross-imports)
│   │   │   ├── auth/           # routes, services, schemas
│   │   │   ├── files/          # upload, storage adapter, metadata, dedup
│   │   │   ├── search/         # FTS, trigram, structured + metadata filters, facets
│   │   │   ├── tags/           # tag CRUD + assign (entity, not the old array col)
│   │   │   ├── correspondents/ # sender/vendor entity CRUD + matching
│   │   │   ├── metadata/       # custom-field catalog + typed values + correction
│   │   │   ├── views/          # saved views (filter-rule sets)
│   │   │   ├── bulk/           # bulk operations on documents
│   │   │   ├── export/         # CSV/XLSX export, zip bulk-download
│   │   │   ├── shares/         # shareable links: authenticated CRUD + public token-resolve
│   │   │   └── idp/            # pipeline: parsing, ocr, extract, gate, classifier, extraction(VLM)
│   │   ├── models/             # SQLAlchemy models (tenant_id on all tenant-owned tables)
│   │   ├── migrations/         # Alembic
│   │   └── tests/              # incl. tenant-isolation tests
│   ├── eval/                   # eval/corpus + run.py (deterministic pass rate + LLM share)
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── app/                    # Next.js routes/pages
│   ├── components/             # reusable UI (shadcn/ui based)
│   ├── lib/                    # api client, supabase client, utils
│   ├── hooks/                  # custom React hooks
│   ├── types/                  # shared TS types
│   └── package.json
└── infra/                      # deployment / IaC configs
```

**Placement rules:** business logic in module `services`, not in route handlers. Shared backend code (models, db, config) lives in `core/` and `models/` so both API and worker import it. Frontend UI primitives in `components/`, data/API logic in `lib/` and `hooks/`. No file bytes anywhere except object storage.

## 6. AI Coding Directives

**Tenancy & security (non-negotiable — highest priority)**
- EVERY tenant-owned table has `tenant_id`. EVERY query runs under the tenant/RLS context. Never write a query, endpoint, or migration that could bypass tenant isolation. **Never disable or weaken RLS.** When unsure whether a change is tenant-safe, stop and ask.
- Never hardcode secrets/credentials — use env vars. Never log secrets or PII. Use parameterized queries. Validate and sanitize all uploads.

**Architecture & cost discipline**
- Respect module boundaries; communicate across modules through service layers, not internal imports.
- Keep request handlers fast — push any OCR/extraction/long work to the worker. No blocking the API.
- Honor the cost-first design: skip OCR when a text layer exists; **the VLM runs ONLY after `gate.py` fails (score < 0.75)** — never call the VLM on the default path. *This rule governs the `"cascade"` extraction strategy specifically; it does not apply to the `"paddle_qwen"` strategy, which is a deliberate, user-approved exception — see the dual-strategy note in §2 and the Tev-Nal decision log in §4.* Improve `extract.py` rules when pass rate is low; never lower the gate threshold to pass. Do not introduce heavy infrastructure (search clusters, extra services) without explicit approval.
- **Retrieval-first & universal:** every file type must be archived, processed (text+thumbnail+metadata), and made searchable; never block ingestion because structured extraction doesn't apply. Search must stay <2s.
- **SaaS-friendly model licensing (hard rule):** any model weights added must be **MIT or Apache-2.0**. Never add AGPL (e.g. YOLOv10) or non-commercial CC-BY-NC (e.g. LayoutLMv3) weights to the product. Use the approved substitutes (TATR, LiLT, PP-Structure, docling, Donut, img2table). New heavy/optional models go behind a feature flag, benchmarked on `eval/corpus` first.
- Respect the MoSCoW scope. If a task drifts into Should/Could/Won't features, flag it before building.

**Code quality**
- Write modular, single-responsibility functions. Follow **DRY** — extract shared logic instead of duplicating.
- Python: full type hints + docstrings on public functions/classes. Frontend: TypeScript + JSDoc on exported functions/components.
- Keep changes minimal and focused on the task. Match existing style; run formatters/linters (ruff + black for Python, eslint + prettier for TS).

**Change safety**
- **Do not delete or rewrite existing working functions without asking first.** Prefer additive, backward-compatible changes.
- All schema changes go through Alembic migrations — never edit the DB or models ad hoc. Every new tenant-owned table needs `tenant_id` + both RLS policy variants in the same migration.
- Add or update tests for new logic, especially tenant-isolation and pipeline tests. Any change to `extract.py`/`gate.py`/parsers: run `eval/run.py` and report **deterministic pass rate** + **LLM share**; a change that improves one field but drops pass rate is a regression. New extraction rules need a fixture doc in `eval/corpus/`.
- **Ask before:** adding a dependency, changing architecture, destructive operations, or touching auth/tenancy/RLS/storage code.

**Working style**
- If required context is missing, ask a focused question rather than guessing. State any assumptions you make inline.
- Explain non-obvious decisions briefly in comments or the response, not in long prose.