# DataWiz Digital Archive System — End-to-End GCP VM Deployment Guide

This document provides a complete, production-grade, step-by-step walkthrough for deploying the **DataWiz Digital Archive System** on a single **Google Cloud Platform (GCP) Compute Engine Virtual Machine (VM)**.

It covers infrastructure provisioning, firewall configuration, environment setup, database alignment, service supervisor setup using `PM2` & `Docker`, and health verification.

---

## 1. System Architecture & Network Ports

The platform runs as a co-located multi-service application inside a single Ubuntu Linux VM, connecting to an external managed PostgreSQL database on Supabase and self-hosted AI endpoints.

| Component | Technology | Internal / Ingress Port | Purpose |
| :--- | :--- | :---: | :--- |
| **Frontend UI** | Next.js 16 (App Router, Standalone mode) | **HTTP Port 3000** (Public) | Web Application User Interface |
| **Backend API** | FastAPI (Python 3.11, Uvicorn ASGI) | **HTTP Port 8000** (Public) | RESTful API & Security chokepoint |
| **RAG Demo App** | Streamlit | **HTTP Port 8501** (Public) | Interactive Text-to-SQL & RAG Dashboard |
| **Worker Engine** | Python RQ (Redis Queue) | Background Process | Asynchronous OCR, VLM & document ingestion |
| **Message Queue** | Redis (`redis:alpine` in Docker) | **Port 6379** (Localhost only) | Task queue for async background jobs |
| **Database** | PostgreSQL (Supabase Managed DB) | External Cloud (Ports 5432/6543) | Persistent metadata & RLS storage |
| **File Storage** | Supabase Storage (`documents` bucket) | External Cloud HTTPS | PDF/Image original document storage |
| **VLM & OCR** | Lightning AI Studio Cloud Endpoints | External Cloud HTTPS | Qwen2.5-VL & PaddleOCR inference |

---

## 2. Step 1: Provisioning the GCP Compute Engine VM

### Option A: Via Google Cloud Console (Web UI)

1. Open the [GCP Compute Engine Console](https://console.cloud.google.com/compute/instances).
2. Click **Create Instance**.
3. Configure the following settings:
   * **Name**: `datawiz-production-vm`
   * **Region**: `asia-southeast1` (Singapore) or your preferred region.
   * **Machine Family**: General Purpose.
   * **Series**: `E2`.
   * **Machine Type**: `e2-medium` (2 vCPUs, 4 GB RAM) or `e2-standard-2` (2 vCPUs, 8 GB RAM).
   * **Boot Disk**: 
     * Operating System: **Ubuntu**
     * Version: **Ubuntu 22.04 LTS** or **24.04 LTS**
     * Size: **30 GB** (Standard Persistent Disk)
   * **Firewall**: Check **Allow HTTP traffic** and **Allow HTTPS traffic**.
4. Click **Create**.

---

### Option B: Via `gcloud` CLI (Terminal)

Run the following command in your local terminal or Google Cloud Shell:

```bash
gcloud compute instances create datawiz-production-vm \
    --zone=asia-southeast1-a \
    --machine-type=e2-medium \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=30GB \
    --tags=http-server,https-server,datawiz-ports
```

---

## 3. Step 2: Configuring GCP VPC Firewall Rules

You must allow incoming web traffic on ports `3000` (Frontend), `8000` (FastAPI Backend), and `8501` (Streamlit RAG).

Run these commands in `gcloud` CLI or Cloud Shell:

```bash
# Allow ingress traffic on ports 3000, 8000, 8501
gcloud compute firewall-rules create allow-datawiz-ports \
    --direction=INGRESS \
    --priority=1000 \
    --network=default \
    --action=ALLOW \
    --rules=tcp:3000,tcp:8000,tcp:8501 \
    --source-ranges=0.0.0.0/0 \
    --target-tags=datawiz-ports,http-server
```

*(Note: Verify your VM's public external IP address in the GCP Console — e.g. `34.142.xx.xx`).*

---

## 4. Step 3: Initial OS Setup & System Dependencies

SSH into your VM:
```bash
gcloud compute ssh datawiz-production-vm --zone=asia-southeast1-a
```

Once connected, update system packages and install Python, Git, Node.js 20 LTS, `uv`, Docker, and build utilities:

```bash
# 1. Update APT packages
sudo apt update && sudo apt upgrade -y

# 2. Install Python 3, venv, git, build utilities
sudo apt install -y python3 python3-venv python3-pip git build-essential curl ca-certificates

# 3. Install Astral uv (Ultra-fast Python manager — automatically handles Python versions)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# 4. Install Node.js 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# 5. Install PM2 globally (Process Manager for production background tasks)
sudo npm install -g pm2

# 6. Install Docker Engine
sudo apt install -y docker.io
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker $USER
```

*Note: After running `usermod`, log out of SSH and log back in (`exit` then `gcloud compute ssh...`) so Docker permissions apply.*

---

## 5. Step 4: Clone Codebase & Setup Services

### 4.1 Clone Repository
```bash
cd ~
git clone https://github.com/teevvr7/Digital_Archive_Research.git
cd Digital_Archive_Research
git checkout main
```

---

### 4.2 Start Redis Container
Launch the Redis Queue container in Docker:

```bash
docker run -d \
  --name redis-queue \
  --restart always \
  -p 6379:6379 \
  redis:alpine
```

Verify Redis is running:
```bash
docker ps
```

---

### 4.3 Configure Backend Environment (`backend/.env`)

Create `backend/.env` using `nano`:
```bash
nano backend/.env
```

Paste the following production configuration (replace `<YOUR_VM_EXTERNAL_IP>` with your VM's public IP):

```env
# ==== Supabase Credentials ====
SUPABASE_URL=https://nyfigvqavhasoarapmtj.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im55ZmlndnFhdmhhc29hcmFwbXRqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA4NjMyNjUsImV4cCI6MjA5NjQzOTI2NX0.oFFicAJj9gUbIkLOq_Ko9wRrv-hBvmn4gCT4pVh-SdA
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im55ZmlndnFhdmhhc29hcmFwbXRqIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MDg2MzI2NSwiZXhwIjoyMDk2NDM5MjY1fQ.GzV9azjaJ0Rxsxn6036YYaMO9WZ3jbMWt-eXu_FlpWI
SUPABASE_JWT_SECRET=EoGa65xnOvZDgdI4KR8ZHIzAMqQkLsi7K+0yBD90UADGXPCcUz0ur5+HJW3gX3+E0n1eG0rJWiAKyghU0aBIFQ==
SUPABASE_STORAGE_BUCKET=documents

# ==== Database Connection ====
# API uses transaction pooler (port 6543)
DATABASE_URL=postgresql+psycopg://app_user.nyfigvqavhasoarapmtj:elonmuskcol%40bw%21thneym%40r@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres
# Alembic uses direct connection (port 5432)
ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:Digital123%40archive@db.nyfigvqavhasoarapmtj.supabase.co:5432/postgres
DB_PREPARE_THRESHOLD=none

# ==== Redis Queue ====
REDIS_URL=redis://localhost:6379/0
IDP_QUEUE_NAME=idp

# ==== External VLM & OCR Endpoints ====
VLM_BASE_URL=https://8001-01ktwv34p98sx3n9n7crzkyezh.cloudspaces.litng.ai/v1
VLM_API_KEY=none
VLM_MODEL=qwen3-vl-4b-instruct
PADDLE_OCR_URL=https://8002-01ktwv34p98sx3n9n7crzkyezh.cloudspaces.litng.ai

# ==== IDP Tuning ====
CONFIDENCE_THRESHOLD=0.7
PROMOTE_AFTER_N=3
VLM_MAX_PAGES=3
MAX_UPLOAD_MB=50

# ==== App Settings ====
CORS_ALLOW_ORIGINS=http://<YOUR_VM_EXTERNAL_IP>:3000,http://localhost:3000,http://127.0.0.1:3000
SENTRY_DSN=
ENV=production
```

---

### 4.4 Configure Frontend Environment (`frontend/.env.local`)

Create `frontend/.env.local` using `nano`:
```bash
nano frontend/.env.local
```

Paste the following configuration:

```env
NEXT_PUBLIC_SUPABASE_URL=https://nyfigvqavhasoarapmtj.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im55ZmlndnFhdmhhc29hcmFwbXRqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA4NjMyNjUsImV4cCI6MjA5NjQzOTI2NX0.oFFicAJj9gUbIkLOq_Ko9wRrv-hBvmn4gCT4pVh-SdA
NEXT_PUBLIC_API_BASE_URL=http://<YOUR_VM_EXTERNAL_IP>:8000/api
```

---

## 6. Step 5: Backend Setup & Database Migrations

### Option 5A: Ultra-Fast Setup with `uv` (Recommended)

```bash
cd ~/Digital_Archive_Research/backend

# 1. Create Virtual Environment (uv automatically downloads Python 3.11 if missing!)
uv venv venv --python 3.11

# 2. Activate Virtual Environment
source venv/bin/activate

# 3. Install dependencies instantly with uv
uv pip install -e ".[worker]"

# 4. Run Alembic Database Migrations
alembic upgrade head
```

---

### Option 5B: Standard Setup with `python3`

If using standard `python3` without `uv`:

```bash
cd ~/Digital_Archive_Research/backend

# 1. Create Virtual Environment
python3 -m venv venv

# 2. Activate Virtual Environment
source venv/bin/activate

# 3. Upgrade pip and install dependencies
pip install --upgrade pip
pip install -e ".[worker]"

# 4. Run Alembic Database Migrations
alembic upgrade head
```

---

## 7. Step 6: Frontend Compilation & Build

```bash
cd ~/Digital_Archive_Research/frontend

# 1. Install Node.js dependencies
npm install

# 2. Build production bundle
npm run build
```

---

## 8. Step 7: Configuring PM2 Supervisor for Production

We use `PM2` to run and manage all 4 system components continuously in the background.

```bash
# 1. Return to repository root
cd ~/Digital_Archive_Research

# 2. Start Backend API on Port 8000
pm2 start "backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000" --name datawiz-backend

# 3. Start Async IDP RQ Worker
pm2 start "backend/venv/bin/python -m app.worker" --name datawiz-worker

# 4. Start Next.js Frontend on Port 3000
pm2 start "npm --prefix frontend run start -- -p 3000" --name datawiz-frontend

# 5. (Optional) Start Streamlit RAG App on Port 8501
pm2 start "backend/venv/bin/streamlit run rag_dev/streamlit_app.py --server.port 8501 --server.address 0.0.0.0" --name datawiz-rag

# 6. Save PM2 Process List
pm2 save

# 7. Configure PM2 to start automatically on VM reboot
sudo env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u $USER --hp /home/$USER
```

---

## 9. Step 8: Post-Deployment Verification

### Check PM2 Running Status
```bash
pm2 status
```

Expected output:
```text
┌──────────────────┬────┬──────┬──────────┬────────┬─────────┬────────┬─────┐
│ App name         │ id │ mode │ status   │ cpu    │ memory  │ uptime │ ... │
├──────────────────┼────┼──────┼──────────┼────────┼─────────┼────────┼─────┤
│ datawiz-backend  │ 0  │ fork │ online   │ 0%     │ 65 MB   │ 2m     │ ... │
│ datawiz-worker   │ 1  │ fork │ online   │ 0%     │ 55 MB   │ 2m     │ ... │
│ datawiz-frontend │ 2  │ fork │ online   │ 0%     │ 80 MB   │ 2m     │ ... │
│ datawiz-rag      │ 3  │ fork │ online   │ 0%     │ 70 MB   │ 2m     │ ... │
└──────────────────┴────┴──────┴──────────┴────────┴─────────┴────────┴─────┘
```

### Healthcheck Verification Commands

Run these `curl` commands to confirm every endpoint responds with `200 OK`:

```bash
# 1. Test Backend API Health
curl http://localhost:8000/api/health
# Expected: {"status":"ok","env":"production"}

# 2. Test Export Meta Endpoint
curl http://localhost:8000/api/export/meta

# 3. Test Frontend Server
curl -I http://localhost:3000
# Expected: HTTP/1.1 200 OK

# 4. Test Streamlit Dashboard
curl -I http://localhost:8501
```

---

## 10. Accessing the System

Open your browser and navigate to:

* **Main Web Application**: `http://<YOUR_VM_EXTERNAL_IP>:3000`
* **FastAPI Interactive Docs**: `http://<YOUR_VM_EXTERNAL_IP>:8000/docs`
* **Streamlit RAG Dashboard**: `http://<YOUR_VM_EXTERNAL_IP>:8501`

---

## 11. Useful Maintenance Commands

```bash
# View live logs for all processes
pm2 logs

# View logs for a specific service
pm2 logs datawiz-backend
pm2 logs datawiz-worker
pm2 logs datawiz-frontend

# Restart services after a git pull
cd ~/Digital_Archive_Research
git pull origin main
cd frontend && npm run build && cd ..
pm2 restart all
```
