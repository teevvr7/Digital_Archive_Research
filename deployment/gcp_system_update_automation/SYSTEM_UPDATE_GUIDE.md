# DataWiz Digital Archive — GCP System Update Guide

This guide provides step-by-step instructions for updating an existing **DataWiz Digital Archive** production instance on Google Cloud Platform (GCP) after making code updates on your local development machine.

---

## 🚀 Quick Summary: 2-Step Developer Update Workflow

Whenever you complete new features or bug fixes locally:

```powershell
# 1. Commit and push your changes to GitHub main branch
git add .
git commit -m "your update commit message"
git push origin main

# 2. Trigger the automated GCP VM update from your local terminal
.\deployment\gcp_system_update_automation\update-gcp.ps1
```

---

## 🛠️ Detailed Update Methods

### Method 1: Automated Local PowerShell Script (Recommended)

Run the update script located at [`deployment/gcp_system_update_automation/update-gcp.ps1`](./update-gcp.ps1) from your local terminal:

```powershell
.\deployment\gcp_system_update_automation\update-gcp.ps1
```

**What this script automatically performs**:
1. Checks for local `gcloud` CLI executable.
2. Connects securely to the GCP VM (`datawiz-production-vm` in zone `asia-southeast1-a`) via SSH.
3. Pulls the latest commits from the GitHub `main` branch.
4. Re-builds the Next.js production bundle inside `frontend/`.
5. Restarts all 3 PM2 supervised processes (`datawiz-backend`, `datawiz-frontend`, `datawiz-worker`).
6. Displays service status and operational endpoints.

---

### Method 2: Manual 1-Line Command from Local Terminal

If you prefer to run the `gcloud` command directly from PowerShell without a helper script:

```powershell
& "$env:LocalAppData\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" compute ssh datawiz-production-vm --zone=asia-southeast1-a --command="cd ~/Digital_Archive_Research && git pull origin main && cd frontend && npm run build && pm2 restart all" --quiet
```

---

### Method 3: Direct Update via GCP Web Console (Cloud Shell / SSH)

If you are logged into the [GCP Web Console](https://console.cloud.google.com):

1. Navigate to **Compute Engine > VM Instances**.
2. Click the **SSH** button next to `datawiz-production-vm`.
3. In the SSH terminal window, paste and run the following commands:

```bash
cd ~/Digital_Archive_Research
git pull origin main
cd frontend
npm run build
pm2 restart all
```

---

## 🔍 Verification & Health Checks

After running an update, verify the application status:

### 1. View PM2 Process Logs
To monitor live logs on the VM:
```bash
# SSH into VM
gcloud compute ssh datawiz-production-vm --zone=asia-southeast1-a

# Check PM2 process table
pm2 status

# View live application logs
pm2 logs
```

### 2. Operational Health Check Endpoints
Replace `<VM_PUBLIC_IP>` with your VM IP:
- **Web UI**: `http://<VM_PUBLIC_IP>`
- **Backend API Health**: `http://<VM_PUBLIC_IP>/api/health`

---

## ⚠️ Troubleshooting Update Issues

| Issue | Cause | Solution |
|---|---|---|
| `gcloud : The term 'gcloud' is not recognized` | `gcloud` CLI not on system PATH | Use the full path: `& "$env:LocalAppData\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"` |
| `git pull` conflict on VM | Uncommitted changes on remote VM | SSH into VM and run `cd ~/Digital_Archive_Research && git reset --hard origin/main` |
| `npm run build` fails | Missing node_modules or dependencies | SSH into VM and run `cd ~/Digital_Archive_Research/frontend && npm install && npm run build` |
