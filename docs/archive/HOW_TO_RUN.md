# Running the DataWiz Digital Archive System

This document outlines the step-by-step instructions to configure, run, and verify the DataWiz Digital Archive platform locally.

---

## 1. Prerequisites

Ensure you have the following installed on your system:
* **Python (≥ 3.11)**
* **Node.js (≥ 18.x) & npm**
* **Redis** (running locally or via Docker)
* **Supabase Account / Project** (for Auth, PostgreSQL, and Storage)

---

## 2. Infrastructure Setup (Supabase & Redis)

### Supabase Setup
1. **Create a Database & Storage Bucket**:
   - Set up a bucket named `documents` (with public access allowed, or configure proper RLS policies).
2. **Retrieve API Credentials**:
   - Go to **Project Settings > API** in the Supabase Dashboard.
   - Collect your **Project URL**, **Anon Key**, **Service Role Key**, and **JWT Secret**.

### Redis Setup
Run Redis locally on port `6379`. If you have Docker, you can run:
```bash
docker run -d --name datawiz-redis -p 6379:6379 redis:alpine
```

---

## 3. Backend Setup

1. **Navigate to the Backend Directory**:
   ```bash
   cd backend
   ```

2. **Initialize Environment Variables**:
   Copy `.env.example` to `.env` and fill in the values you obtained from Supabase:
   ```bash
   cp .env.example .env
   ```

3. **Install Dependencies**:
   Create a virtual environment, activate it, and install all dependencies:
   ```bash
   python -m venv venv
   # On Windows (PowerShell):
   .\venv\Scripts\Activate.ps1
   # On Linux/macOS:
   source venv/bin/activate

   # Install core and worker dependencies:
   pip install -e .[worker,dev]
   ```

4. **Run Database Migrations**:
   Run Alembic to apply RLS schemas, seed document types, and execute necessary upgrades:
   ```bash
   alembic upgrade head
   ```

---

## 4. Running the System

To run the full system, you must start three separate components: **Backend API**, **Async Worker**, and **Frontend Client**.

### A. Start the Backend API (FastAPI)
From the `backend/` directory with your virtual environment activated:
```bash
uvicorn app.main:app --port 8001 --reload
```
* **Swagger Documentation**: Available at `http://localhost:8001/api/docs` once running.

### B. Start the Async IDP Worker (RQ)
From the `backend/` directory with your virtual environment activated:
```bash
python -m app.worker
```
* **Windows Support**: The system automatically detects Windows and starts in `SimpleWorker` mode to avoid fork exceptions.
* **Linux/macOS Support**: Starts standard `Worker` with job retry scheduling enabled.

### C. Start the Frontend (Next.js)
1. Navigate to the `frontend/` directory:
   ```bash
   cd ../frontend
   ```
2. Create an environment file `.env.local` containing:
   ```env
   NEXT_PUBLIC_SUPABASE_URL=https://your-project-ref.supabase.co
   NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
   NEXT_PUBLIC_API_BASE_URL=http://localhost:8001/api
   ```
3. Install dependencies and start the development server:
   ```bash
   npm install
   npm run dev
   ```
* **Access the UI**: Open your browser and navigate to `http://localhost:3000`.

---

## 5. Testing & Verification

### Running Automated Tests
Run the Python test suite to ensure tenant isolation, search, and extraction routes function correctly:
```bash
cd backend
# Set direct database url for isolation test seeds (if testing database-level RLS)
# On Windows (PowerShell):
$env:ALEMBIC_DATABASE_URL="postgresql+psycopg://..." 
# On Linux/macOS:
export ALEMBIC_DATABASE_URL="postgresql+psycopg://..."

# Run the test suite:
.\venv\Scripts\python -m pytest
```

### Strategy Switching (Paddle-Qwen vs. Default VLM)
1. Open the UI at `http://localhost:3000`.
2. Go to the **Settings > IDP Control Center** tab.
3. Choose a document type (e.g., *Invoice*).
4. Select the **PaddleOCR-VL + Qwen-VL** extraction strategy, customize the target schema JSON or prompt hints, and click **Save Configuration**.
5. Upload an invoice at the upload dashboard page and verify that the logs show the Paddle dispatcher executing the custom strategy.
