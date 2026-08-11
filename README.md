# DataWiz IDP & Digital Archiving Platform (MVP v1.0.0)

An enterprise-grade **Intelligent Document Processing (IDP) and AI-Powered Digital Archiving System** built for multi-tenant document ingestion, automated OCR/VLM field extraction, dynamic schema management, spreadsheet grid view, and hybrid search.

---

## 🌟 Overview & Key Features

The DataWiz Digital Archiving Platform provides a complete end-to-end pipeline for converting unstructured physical and digital documents (PDFs, images, scans) into structured, searchable database records.

### Core Capabilities
1. **Multi-Engine Ingestion Pipeline**:
   - High-accuracy optical character recognition and visual-language parsing powered by **PaddleOCR** and **Qwen3-VL-4B-Instruct** (via remote GPU inference server) with automated fallback mechanisms.
   - Support for single and multi-page PDFs, high-resolution scans, PNGs, and JPEGs.
   - Clear pipeline document states (`queued`, `extracting_text`, `ocr_processing`, `ai_extraction`, `needs_review`, `completed`, `failed`).
2. **IDP Control Center & Dynamic Schema Engine**:
   - Custom document type configuration (*Invoice*, *Receipt*, *Bank Statement*, *Tax Form*, *Utility Bill*, custom types).
   - Dynamic target JSON schema definition and prompt hint customization per document type.
   - Flexible template matching engine (automatic document template classification based on structural fingerprints and key vendor attributes).
3. **Multi-Tenant Security & Isolation**:
   - PostgreSQL Row Level Security (RLS) policies guaranteeing complete data and document isolation between tenant accounts (`app.current_tenant`).
4. **Hybrid Search & RAG Engine**:
   - Combined keyword full-text search (`tsvector`), fuzzy trigram similarity matching (`pg_trgm`), and vector semantic search (`pgvector`).
5. **Interactive UI & Spreadsheet View**:
   - Built with **Next.js 16 (App Router)** and **TailwindCSS**.
   - Interactive Document Inbox, Document Inspector, IDP Settings Control Center, Search Interface, and Spreadsheet Grid View for bulk metadata editing.

---

## 🏗️ System Architecture

```
                                  ┌────────────────────────────────┐
                                  │      Next.js 16 Frontend       │
                                  │    (Port 3000 / App Router)    │
                                  └───────────────┬────────────────┘
                                                  │ HTTP / REST API
                                                  ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 FastAPI Backend (Port 8000)                                      │
│                                                                                                  │
│   ┌─────────────────────┐    ┌─────────────────────┐    ┌────────────────────────────────────┐   │
│   │   Auth & Security   │    │  IDP Router & CRUD  │    │      Search & Hybrid Query         │   │
│   │  (Supabase JWT/RLS) │    │ (Templates/Schemas) │    │  (FTS + pg_trgm + pgvector)        │   │
│   └─────────────────────┘    └─────────────────────┘    └────────────────────────────────────┘   │
└───────────────┬─────────────────────────────────┬────────────────────────────────────────────────┘
                │                                 │
                ▼ Async Task Enqueue              ▼ Database Connection (Psycopg3)
     ┌─────────────────────┐           ┌───────────────────────────────────────────────────────────┐
     │  Redis Queue (RQ)   │           │                 Supabase PostgreSQL DB                    │
     │     (Port 6379)     │           │  - Row Level Security (RLS) Isolation                     │
     └──────────┬──────────┘           │  - Full-Text Search (search_tsv) & pg_trgm Trigram        │
                │                      │  - Document Models, Templates, Extractions & JSONB        │
                ▼                      └──────────────────────────────┬────────────────────────────┘
┌──────────────────────────────┐                                      │
│   Async IDP Worker (RQ)      │                                      │
│  (app.worker / SimpleWorker) │                                      │
└──────────────┬──────────────┘                                      │
                │ Remote AI Inference Calls                           │ Storage Upload / Signed URLs
                ▼                                                     ▼
┌──────────────────────────────┐                       ┌───────────────────────────────────────────┐
│ Remote AI Inference Server   │                       │          Supabase Storage Bucket          │
│ (PaddleOCR + Qwen3-VL-4B)    │                       │                ('documents')              │
└──────────────────────────────┘                       └───────────────────────────────────────────┘
```

---

## 🛠️ Technology Stack

| Layer | Technologies |
|---|---|
| **Frontend UI** | Next.js 16 (App Router), React 19, TypeScript, TailwindCSS, Lucide Icons, Supabase JS Client |
| **Backend API** | Python 3.11+, FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2.0, Alembic |
| **Async Queue & Worker** | Redis 7, Python RQ (`rq.Worker` / `rq.SimpleWorker` for Windows compatibility) |
| **Database & Security** | PostgreSQL 15+, Supabase (Auth, RLS Policies, Storage), `pgvector`, `pg_trgm` |
| **AI / OCR / VLM** | PaddleOCR, Qwen3-VL-4B-Instruct (Remote GPU Server on Lightning AI), OpenAI SDK |
| **Process Supervision** | PM2 (for Cloud VM), PowerShell / Systemd |

---

## 📁 Repository Directory Structure

```
Digital_Archive_Research/
├── backend/                        # FastAPI Python Backend & Async Worker
│   ├── app/
│   │   ├── core/                   # Core config, DB session, security middleware, JWT auth
│   │   ├── migrations/             # Alembic migration scripts (0001_initial through 0019)
│   │   ├── models/                 # SQLAlchemy ORM models (18 database entities)
│   │   ├── modules/                # Domain routers & services (files, idp, search, templates, etc.)
│   │   ├── tests/                  # Pytest automated test suite
│   │   ├── main.py                 # FastAPI application entry point
│   │   └── worker.py               # Async RQ worker entry point
│   ├── pyproject.toml              # Dependencies & package specification
│   └── .env.example                # Backend environment variable template
│
├── frontend/                       # Next.js 16 Web Application
│   ├── app/
│   │   ├── (app)/                  # Authenticated app routes (dashboard, documents, search, settings, spreadsheet)
│   │   └── login/                  # Auth routes (login, signup, reset-password)
│   ├── components/                 # Reusable UI components & dialogs
│   ├── lib/                        # API client (api.ts), Supabase client, utilities
│   ├── package.json                # Node dependencies & scripts
│   └── .env.local                  # Frontend environment variable template
│
├── ai_server/                      # Remote AI Inference Server scripts (PaddleOCR + FastAPI)
│   └── remote_paddle_server.py     # GPU inference service deployed on remote server
│
├── docs/                           # Master Technical & Developer Documentation
│   ├── DEVELOPER_GUIDE.md          # Complete local setup, prerequisites, and troubleshooting
│   ├── ARCHITECTURE_AND_DATABASE.md# In-depth system architecture & database schema specification
│   └── archive/                    # Preserved historical specs, incident logs, and developer notes
│
├── deployment/                     # Production GCP Deployment Suite (Local CLI & Cloud Console)
│   ├── README.md                   # Master deployment index
│   ├── local_cli_automation/       # Strategy 1: Local Terminal (PowerShell + gcloud)
│   └── gcp_cloud_console_automation/# Strategy 2: GCP Web Console / Cloud Shell
├── start-system.ps1                # Automated PowerShell system launcher for local development
├── CLAUDE.md                       # AI developer reference guide
└── .gitignore                      # Git exclusion rules
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- **Python ≥ 3.11**
- **Node.js ≥ 18.x & npm**
- **Redis Server** (Port `6379`)
- **Supabase Project** (PostgreSQL Database & Storage Bucket `documents`)

### 2. Automated One-Command Startup (Windows PowerShell)
From the repository root directory:
```powershell
.\start-system.ps1
```
This script will automatically check virtual environments, install missing dependencies, and launch the **Backend API** (port 8000), **Async Worker**, and **Frontend** (port 3000) in separate process windows.

### 3. Manual Step-by-Step Launch
For detailed step-by-step installation, database migration commands, and environment setup, consult the **[Developer Guide](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/docs/DEVELOPER_GUIDE.md)**.

---

## 📚 Master Documentation Index

| Guide | Description |
|---|---|
| **[Developer Guide](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/docs/DEVELOPER_GUIDE.md)** | Step-by-step local development setup, environment variables, running migrations, running tests, and troubleshooting known issues. |
| **[Architecture & Database Spec](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/docs/ARCHITECTURE_AND_DATABASE.md)** | Comprehensive breakdown of system components, OCR/VLM extraction pipelines, IDP template matching engine, hybrid search, and full PostgreSQL schema with RLS policies. |
| **[GCP Deployment Suite](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/deployment/README.md)** | Production GCP deployment automation suite (Strategy 1: Local PowerShell CLI; Strategy 2: GCP Cloud Console & Cloud Shell). |

---

## ⚡ Core API Endpoints

Once the backend is running, interactive OpenAPI/Swagger documentation is available at `http://localhost:8000/docs`.

Key API Route Groups:
- **`GET /api/documents`**: List and filter documents (supports sorting, pagination, status filtering, inbox mode).
- **`POST /api/documents/upload`**: Upload document files for background IDP processing.
- **`POST /api/idp/process/{id}`**: Trigger manual IDP processing job for a document.
- **`GET /api/idp/config/templates`**: Fetch document templates and target schema definitions.
- **`PUT /api/idp/config/templates/{id}`**: Save updated JSON schemas and prompt hints for a document template.
- **`GET /api/search`**: Execute hybrid search over ingested documents (supports FTS, trigram, and vector modes).
- **`GET /api/export`**: Export structured document metadata to CSV/Excel formats.

---

## 🔒 Security & Data Isolation
The platform implements defense-in-depth security:
1. **JWT Verification**: Every request is authenticated against Supabase JWT public keys using `httpx` and `PyJWKSet`.
2. **PostgreSQL RLS**: Database transactions execute `SET LOCAL app.current_tenant = '{tenant_id}'`, activating native Row Level Security policies across all queries.
3. **CORS Security**: Strict allowed origins set via `CORS_ALLOW_ORIGINS` in `.env`.

---

## 📄 License & Maintainer Handoff

This codebase represents the completed MVP implementation for the Intelligent Document Processing & Digital Archiving Research platform.

For future developers extending this platform, please start by reading **[docs/DEVELOPER_GUIDE.md](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/docs/DEVELOPER_GUIDE.md)** and **[docs/ARCHITECTURE_AND_DATABASE.md](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/docs/ARCHITECTURE_AND_DATABASE.md)**.
