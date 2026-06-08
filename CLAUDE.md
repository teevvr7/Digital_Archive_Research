# CLAUDE.md

> Context file for AI coding assistants. Read this before writing or modifying any code.

## 1. Project Overview

A multi-tenant, SaaS-based AI-supported **digital archive system** with an **Intelligent Document Processing (IDP)** module. Users upload documents (PDF, scanned PDF, images); the system stores them securely, extracts text and structured data, and makes everything fast and accurate to search and retrieve. **Primary goal:** a cost-efficient archive where the AI layer (~10–15% of logic) enriches a solid traditional-SaaS core (~85–90%). Deployed for Malaysia (PDPA-aware). **Cost-efficiency in storage and AI processing is the #1 priority in every decision.**

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

**Search** (no external search cluster)
- `tsvector` full-text search over extracted text
- `pg_trgm` for fuzzy filename matching
- `JSONB` + GIN indexes for metadata filtering

**IDP pipeline (worker)**
- Parsing: **LiteParse** (LlamaIndex, Rust-based) — layout-aware text + bounding boxes + built-in OCR fallback. Skips OCR when a text layer exists (biggest cost saver).
- Rasterize only: **PyMuPDF** — page → PNG for the VLM input (not for text extraction)
- Structured extraction: **vLLM on Lightning AI Studio** (OpenAI-compatible endpoint, Qwen2.5-VL class), outputs **JSON directly**. Doc types are **dynamic** — stored as DB data, never hardcoded. Unknown/novel docs go to VLM; system learns templates and promotes to deterministic after N confirmations.
- Self-learning loop: `document_types` + `document_templates` tables capture learned layouts. `extractions` table records every attempt — powers exception queue (low-confidence rows) and promote-after-N.

**Frontend**
- **Next.js / React** + TypeScript, **shadcn/ui** component kit. Keep UI minimal.

**Ops:** Single region (Malaysia or Singapore). Sentry for error tracking.

**Key patterns**
- Async-first: uploads return instantly; all heavy IDP work runs in the worker, never in request handlers.
- Pooled multi-tenancy via RLS — `tenant_id` on every tenant-owned row, enforced at the DB.
- IDP cost cascade (full version is post-MVP): triage → classify/fingerprint → cheap deterministic extract OR VLM-to-JSON for novel docs → confidence gate → store/index. The GPU runs only on novelty.

## 3. Core Features (MVP Must-Haves)

- Authentication & login (basic admin/user roles)
- Multi-tenancy via Postgres RLS (`tenant_id` everywhere, DB-enforced isolation)
- File upload: PDF, scanned PDF, images
- Secure object storage + metadata records
- Async processing pipeline (queue + worker)
- Text extraction: text-layer (PyMuPDF) + OCR fallback (PaddleOCR)
- Structured extraction thin slice: VLM-to-JSON for **1–2 document types** against a fixed schema
- Search & retrieval: fuzzy filename, full-text content, metadata filter
- Document viewer + original download
- Basic web UI (upload, list, search, view)

## 4. Roadmap & Current Phase

| Sprint | Weeks | Theme | Deliverable |
|---|---|---|---|
| 0 | 1 | Foundations | Walking skeleton: login works, RLS schema live, OCR+VLM spike on 1 doc |
| 1 | 2–3 | Core SaaS & ingestion | Upload → store → list → download; tenant isolation proven by test |
| 2 | 4–5 | Extraction pipeline | Async text extraction (text-layer + OCR), text stored & indexed |
| 3 | 6–7 | Search + structured IDP | Search <2s; supported doc types return correct JSON |
| 4 | 8 | Hardening & security | All journeys pass; RLS isolation tests green; no critical bugs |
| 5 | 9 | Pilot & launch | Pilot client live on real docs; KPIs instrumented |

**➡️ CURRENT PHASE: Sprint 1 — Core SaaS & Ingestion (Milestone B in progress).**

**Decisions locked:**
- Infrastructure: Supabase (DB + Auth + Storage), Redis + RQ (queue), vLLM on Lightning AI Studio
- Doc types: dynamic (DB data, not code); self-learning IDP pipeline
- JWT: HS256 verified with project secret; ES256/RS256 JWKS-based verification also supported

**Milestone A ✅ complete:** Login → `/auth/bootstrap` → tenant + user rows created in DB → dashboard loads.

**Milestone B next steps (in progress):**
1. `backend/app/modules/files/` — `service.py` (upload/list/get/download/dashboard) + `router.py`
2. Register files + dashboard routers in `main.py`
3. `frontend/lib/format.ts` (shared formatters) + `frontend/lib/auth.tsx` (AuthProvider/guard)
4. Wire dashboard, documents list, document detail, upload pages to real API (replace mock data)
5. Run `pytest test_tenant_isolation.py test_contract_camelcase.py` — must be green before B ships

**Out of scope for MVP (do NOT build without explicit approval):** auto-classification, deterministic extraction path, type "promotion" UI, client template manager, cold-tiering, analytics, public API, microservices, Elasticsearch, multi-region, SSO/SAML, mobile app.

**Phase 2 (post-MVP, data model already built for it):** real auto-classify + fingerprint, deterministic CPU extractor, promote-after-N, confidence-gate tuning, exception-review UI, pgvector semantic template matching.

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
│   │   │   ├── files/          # upload, storage adapter, metadata
│   │   │   ├── search/         # FTS, trigram, metadata filters
│   │   │   └── idp/            # pipeline orchestration, ocr/, extraction/, schemas
│   │   ├── models/             # SQLAlchemy models (tenant_id on all tenant-owned tables)
│   │   ├── migrations/         # Alembic
│   │   └── tests/              # incl. tenant-isolation tests
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
- Honor the cost-first design: skip OCR when a text layer exists; only invoke the GPU/VLM on novel/low-confidence docs. Do not introduce heavy infrastructure (search clusters, extra services, new SaaS dependencies) without explicit approval.
- Respect the MoSCoW scope. If a task drifts into Should/Could/Won't features, flag it before building.

**Code quality**
- Write modular, single-responsibility functions. Follow **DRY** — extract shared logic instead of duplicating.
- Python: full type hints + docstrings on public functions/classes. Frontend: TypeScript + JSDoc on exported functions/components.
- Keep changes minimal and focused on the task. Match existing style; run formatters/linters (ruff + black for Python, eslint + prettier for TS).

**Change safety**
- **Do not delete or rewrite existing working functions without asking first.** Prefer additive, backward-compatible changes.
- All schema changes go through Alembic migrations — never edit the DB or models ad hoc.
- Add or update tests for new logic, especially tenant-isolation and pipeline tests.
- **Ask before:** adding a dependency, changing architecture, destructive operations, or touching auth/tenancy/RLS/storage code.

**Working style**
- If required context is missing, ask a focused question rather than guessing. State any assumptions you make inline.
- Explain non-obvious decisions briefly in comments or the response, not in long prose.