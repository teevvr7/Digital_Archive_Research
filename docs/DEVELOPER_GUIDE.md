# Master Developer Handoff & Operations Guide

This guide provides comprehensive instructions for onboarding new developers, setting up the local development environment, running database migrations, executing tests, and troubleshooting known engineering edge cases.

---

## 📋 1. System Prerequisites

Ensure your workstation has the following software installed before proceeding:

| Dependency | Minimum Version | Notes |
|---|---|---|
| **Python** | `3.11.x` | Ensure `python` and `pip` are on your system PATH. |
| **Node.js** | `18.x` or `20.x` | Recommended LTS release with `npm` included. |
| **Redis** | `7.x` | Running locally or via Docker on port `6379`. |
| **Supabase Project** | Cloud or Self-Hosted | PostgreSQL 15+ instance with `pgvector` and `pg_trgm` extensions enabled. |
| **Git** | `2.x` | Source code management. |

---

## 🛠️ 2. Environment Configuration & Setup

### A. Infrastructure Preparation (Supabase & Redis)

#### 1. Supabase Setup
- Log in to your [Supabase Dashboard](https://supabase.com) and select/create a project.
- **Storage Bucket**: Navigate to **Storage** and create a public/authenticated bucket named **`documents`**.
- **API Credentials**: Navigate to **Project Settings > API** and copy:
  - Project URL (`SUPABASE_URL`)
  - Anon Public Key (`SUPABASE_ANON_KEY`)
  - Service Role Key (`SUPABASE_SERVICE_ROLE_KEY`)
  - JWT Secret (`SUPABASE_JWT_SECRET`)
- **Connection Pooler Strings**: Navigate to **Project Settings > Database > Connection String**:
  - Direct / Session Pooler URL (Port `5432`, used for Alembic migrations)
  - Transaction Pooler URL (Port `6543`, used for runtime API connection pooling)

#### 2. Redis Setup
Start a Redis container locally on port `6379`:
```bash
docker run -d --name datawiz-redis -p 6379:6379 redis:alpine
```
*(Verify Redis is running by executing `docker exec -it datawiz-redis redis-cli ping`, which should return `PONG`).*

---

### B. Backend Setup & Configuration

1. **Navigate to Backend Directory**:
   ```bash
   cd backend
   ```

2. **Create Environment File (`backend/.env`)**:
   Copy `.env.example` to `.env` and fill in your Supabase & system parameters:
   ```bash
   cp .env.example .env
   ```

   **Full `backend/.env` Schema Reference**:
   ```env
   # ==== Supabase (ENV 1 Credentials) ====
   SUPABASE_URL=https://your-project-id.supabase.co
   SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   SUPABASE_JWT_SECRET=your-supabase-jwt-secret-string
   SUPABASE_STORAGE_BUCKET=documents

   # ==== Database Connection (IPv4 Pooler for Cloud & Local Compatibility) ====
   # API uses transaction pooler (port 6543, app_user role)
   DATABASE_URL=postgresql+psycopg://app_user.your-project-id:your-password@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres
   # Alembic uses session pooler (port 5432, postgres role, IPv4 compatible)
   ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres.your-project-id:your-password@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres
   DB_PREPARE_THRESHOLD=none

   # ==== Redis Queue ====
   REDIS_URL=redis://localhost:6379/0
   IDP_QUEUE_NAME=idp

   # ==== External VLM & OCR Endpoints ====
   VLM_BASE_URL=https://your-remote-gpu-server-endpoint.cloudspaces.litng.ai/v1
   VLM_API_KEY=none
   VLM_MODEL=qwen3-vl-4b-instruct
   PADDLE_OCR_URL=https://your-remote-gpu-server-endpoint.cloudspaces.litng.ai

   # ==== IDP Tuning ====
   CONFIDENCE_THRESHOLD=0.7
   PROMOTE_AFTER_N=3
   VLM_MAX_PAGES=3
   MAX_UPLOAD_MB=50

   # ==== App Settings ====
   CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://[::1]:3000
   ENV=development
   ```

3. **Install Python Dependencies**:
   Create a virtual environment and install backend + worker dependencies:
   ```bash
   # Create virtualenv
   python -m venv venv

   # Activate virtualenv
   # On Windows (PowerShell):
   .\venv\Scripts\Activate.ps1
   # On Linux/macOS:
   source venv/bin/activate

   # Install editable package with worker & dev dependencies
   pip install -e .[worker,dev]
   ```

4. **Run Database Migrations**:
   Apply all Alembic migration scripts to upgrade the PostgreSQL schema to head:
   ```bash
   alembic upgrade head
   ```
   *(This creates tables, Row Level Security policies, indexes, and initial document type seeds).*

---

### C. Frontend Setup & Configuration

1. **Navigate to Frontend Directory**:
   ```bash
   cd ../frontend
   ```

2. **Create Local Environment File (`frontend/.env.local`)**:
   Create a `.env.local` file containing:
   ```env
   NEXT_PUBLIC_SUPABASE_URL=https://your-project-id.supabase.co
   NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api
   ```

3. **Install Node Dependencies & Start Development Server**:
   ```bash
   npm install
   npm run dev
   ```
   *(Frontend web application will be accessible at `http://localhost:3000`).*

---

## 🏃 3. Running the System

You can run the entire platform using either the automated launcher script or 3 separate terminal processes.

### Method A: Automated One-Command Script (Windows PowerShell)
From the root directory:
```powershell
.\start-system.ps1
```
This script automatically checks dependencies, activates virtual environments, and launches 3 parallel PowerShell processes for the Backend API (`:8000`), Async IDP Worker, and Next.js Frontend (`:3000`).

### Method B: Manual 3-Terminal Launch

1. **Terminal 1 — Backend API (FastAPI)**:
   ```bash
   cd backend
   .\venv\Scripts\Activate.ps1   # (or source venv/bin/activate)
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
   - Swagger OpenAPI Documentation: `http://localhost:8000/docs`

2. **Terminal 2 — Async Worker (RQ)**:
   ```bash
   cd backend
   .\venv\Scripts\Activate.ps1   # (or source venv/bin/activate)
   python -m app.worker
   ```
   - Auto-detects OS: Runs `SimpleWorker` on Windows and standard `Worker` on Linux.

3. **Terminal 3 — Frontend (Next.js)**:
   ```bash
   cd frontend
   npm run dev
   ```
   - Web App UI: `http://localhost:3000`

---

## 🧪 4. Automated Testing & Verification

Run the backend Pytest suite to verify API routes, search logic, and multi-tenant RLS isolation:

```bash
cd backend
.\venv\Scripts\Activate.ps1

# Run full test suite
pytest

# Run specific test modules
pytest app/tests/test_tenant_isolation.py
pytest app/tests/test_search_service.py
pytest app/tests/test_idp_tenant_isolation.py
```

---

## ⚠️ 5. Known Engineering Edge Cases & Troubleshooting

### Issue 1: CORS Preflight Block (`TypeError: Failed to fetch`) on New Ports
- **Symptom**: Frontend calls to `/api/idp/config/templates` or `/api/search` fail with `TypeError: Failed to fetch` in the browser console.
- **Root Cause**: Backend settings are memoized via `@lru_cache` in `backend/app/core/config.py`. If `CORS_ALLOW_ORIGINS` in `backend/.env` is edited while Uvicorn is running, FastAPI will not pick up the change until restarted.
- **Solution**: Completely stop the Uvicorn process (`Ctrl+C`) and re-launch `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`.

### Issue 2: GCP VM Connection Failure During Alembic Migrations (`Network is unreachable`)
- **Symptom**: Running `alembic upgrade head` on a GCP Compute Engine VM throws `psycopg.OperationalError: connection to server failed: Network is unreachable`.
- **Root Cause**: Direct Supabase hostnames (`db.nyfigvqavhasoarapmtj.supabase.co:5432`) resolve to IPv6 addresses. GCP VM instances lack default IPv6 egress gateways on standard VPC networks.
- **Solution**: Always set `ALEMBIC_DATABASE_URL` in `backend/.env` to Supabase's IPv4 Pooler URL (`aws-1-ap-northeast-2.pooler.supabase.com:5432`), which routes over IPv4.

### Issue 3: PostgreSQL `word_similarity` Function Not Found (`UndefinedFunction`)
- **Symptom**: Full-text fuzzy search queries crash backend with `psycopg.errors.UndefinedFunction: function word_similarity(character varying, text) does not exist`.
- **Root Cause**: Supabase installs `pg_trgm` in the `extensions` schema. PgBouncer's transaction pooler (port 6543) resets session state between transactions, so `ALTER ROLE app_user SET search_path` does not persist across pooled connections.
- **Solution**: Handled automatically in `backend/app/core/db.py` via a SQLAlchemy connection event listener:
  ```python
  @event.listens_for(engine, "connect")
  def _set_search_path(dbapi_connection, connection_record):
      cursor = dbapi_connection.cursor()
      cursor.execute('SET search_path TO "$user", public, extensions')
      cursor.close()
  ```

### Issue 4: RLS Policy Blocks Global System Document Types
- **Symptom**: IDP Control Center in Settings fails to load default document templates for new tenants.
- **Root Cause**: System default document types (`invoice`, `receipt`, etc.) have `tenant_id = NULL`. Strict RLS policies filtering by `tenant_id = app.current_tenant` exclude `NULL` tenant rows.
- **Solution**: Enforce RLS policy `tenant_isolation_document_types` allowing `tenant_id IS NULL OR tenant_id = current_setting('app.current_tenant', true)::uuid`.

### Issue 5: Transaction GUC Reset & RLS Block During `db.refresh()` (`500 Internal server error` on Template Save)
- **Symptom**: `PUT /idp/config/templates/{id}` returns `500 {"detail":"Internal server error"}` (or `TypeError: Failed to fetch` on frontend).
- **Root Cause**: Route handlers called `db.commit()` inside the endpoint before `db.refresh()`. The transaction-local tenant GUC (`app.current_tenant`, set via `SET LOCAL`) was automatically cleared when `db.commit()` ended the transaction. Subsequent `db.refresh()` SELECT queries failed under Row-Level Security (RLS) because no tenant context remained, raising `InvalidRequestError: Instance has been deleted, or its row is otherwise not present`.
- **Solution**: Route handlers using `get_tenant_db` must call `db.flush()` instead of `db.commit()`. `db.flush()` writes changes within the active transaction (preserving the GUC for `db.refresh()`), allowing the `get_tenant_db` dependency to handle final commit upon request completion.

### Issue 6: Route Shadowing on FastAPI Parameterized Endpoints (`422` or `500` on `POST /idp/config/document-types`)
- **Symptom**: Creating a new document type via `POST /idp/config/document-types` returns a `422 Unprocessable Entity` (`uuid_parsing` error for path parameter `document_type_id="document-types"`) or `500 Internal server error`.
- **Root Cause**: FastAPI evaluates routes in exact registration order. Generic parameterized path `@router.post("/{document_type_id}")` was registered *before* static path `@router.post("/document-types")`. FastAPI matched `/document-types` against `/{document_type_id}`, setting `document_type_id = "document-types"` and attempting UUID parsing.
- **Solution**: In FastAPI routers, always define specific static paths (e.g. `@router.post("/document-types")`) **before** generic parameter paths (e.g. `@router.post("/{document_type_id}")`).

---

## 📈 6. Production Deployment Overview

For instructions on deploying the full stack to a single Google Cloud Platform (GCP) Compute Engine VM with PM2 process supervision, Caddy reverse proxy, and SSL, refer to **[deployment/README.md](file:///c:/Users/pnala/Desktop/IDP_Archive/idp_codebase/Digital_Archive_Research/deployment/README.md)**.

