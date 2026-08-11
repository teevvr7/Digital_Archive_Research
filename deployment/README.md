# DataWiz Digital Archive — Deployment Suite

This directory contains the production-grade deployment scripts and comprehensive documentation for deploying the **DataWiz Digital Archive & IDP System** on **Google Cloud Platform (GCP)**.

---

## Deployment Strategies Available

| Strategy | Recommended Use Case | Prerequisites | Folder / Guide Link |
|:---|:---|:---|:---|
| **Strategy 1: Local Terminal & CLI Automation** | Automated deployment driven directly from your Windows machine (PowerShell) | Windows PowerShell, `gcloud` CLI installed & authenticated | [`deployment/local_cli_automation/`](./local_cli_automation/LOCAL_CLI_DEPLOYMENT_GUIDE.md) |
| **Strategy 2: GCP Cloud Console & Cloud Shell** | Web-based 1-click deployment from GCP Web Console or Google Cloud Shell | GCP Web Console access, no local software required | [`deployment/gcp_cloud_console_automation/`](./gcp_cloud_console_automation/CLOUD_CONSOLE_DEPLOYMENT_GUIDE.md) |

---

## System Architecture Overview

Both strategies deploy a **co-located production architecture** on a single Compute Engine Virtual Machine (`e2-standard-2`, Ubuntu 22.04 LTS):

- **Reverse Proxy**: Caddy Web Server binding public ports `80` (HTTP) and `443` (HTTPS).
  - Routes `/api/*` to FastAPI Backend on port `8000`.
  - Routes `/*` to Next.js Frontend on port `3000`.
- **Application Processes**: Supervised by `PM2` (auto-restarts on reboot).
  - `datawiz-backend`: FastAPI Uvicorn ASGI server.
  - `datawiz-worker`: Python RQ async document ingestion & OCR engine.
  - `datawiz-frontend`: Next.js 16 standalone production build.
- **Message Queue**: Redis Alpine running in Docker, bound strictly to `127.0.0.1:6379`.
- **Database & Storage**: External Supabase Managed PostgreSQL (IPv4 Pooler port `6543`) & Supabase Storage.
- **AI Engine**: Remote GPU endpoints (Lightning AI Qwen2.5-VL & PaddleOCR).

---

## Directory Structure

```text
deployment/
├── README.md                                 # Master deployment index (this file)
├── SYSTEM_UPDATE_GUIDE.md                    # Developer guide for updating existing GCP VM
├── update-gcp.ps1                            # 1-click PowerShell update script for existing GCP VM
├── local_cli_automation/                     # Strategy 1: Local PowerShell + gcloud CLI initial setup
│   ├── deploy-gcp.ps1                        # Master local PowerShell initial orchestrator
│   ├── setup-vm.sh                           # VM initialization & build shell script
│   └── LOCAL_CLI_DEPLOYMENT_GUIDE.md         # Full documentation for local CLI deployment
└── gcp_cloud_console_automation/             # Strategy 2: GCP Web Console / Cloud Shell initial setup
    ├── cloud_shell_deploy.sh                 # 1-click deployment script for Cloud Shell
    ├── startup_script_metadata.sh            # GCP Compute Engine Startup Metadata script
    └── CLOUD_CONSOLE_DEPLOYMENT_GUIDE.md     # Full documentation for Cloud Console deployment
```
