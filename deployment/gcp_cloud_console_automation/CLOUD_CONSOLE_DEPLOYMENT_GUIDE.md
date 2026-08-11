# Strategy 2: GCP Cloud Console & Cloud Shell Automated Deployment

This guide documents how to deploy the **DataWiz Digital Archive System** directly using **Google Cloud Platform (GCP) Web Console** or **Google Cloud Shell** without requiring any software installed on your local computer.

---

## Deployment Methods Available

| Method | Where It Runs | Description |
|:---|:---|:---|
| **Method A: Google Cloud Shell (1-Click Command)** | Browser Terminal ([shell.cloud.google.com](https://shell.cloud.google.com)) | Run a single command in Google Cloud Shell. It provisions the VM, copies setup scripts, and executes deployment automatically. |
| **Method B: GCP Web Console UI (Startup Metadata)** | GCP Web Console UI ([console.cloud.google.com](https://console.cloud.google.com)) | Paste a single script into the VM creation form. Google Cloud automatically provisions and boots the entire application upon startup. |

---

## Method A: Deployment via Google Cloud Shell (Recommended 1-Click)

### Step 1: Open Google Cloud Shell
1. Open your browser and navigate to **[https://shell.cloud.google.com](https://shell.cloud.google.com)**.
2. Select your project `archivingproj01` at the top.

### Step 2: Run the Deployment Command
Paste and run the following 1-click command inside Cloud Shell:

```bash
curl -sSL https://raw.githubusercontent.com/teevvr7/Digital_Archive_Research/main/deployment/gcp_cloud_console_automation/cloud_shell_deploy.sh | bash
```

### What Method A Automates
1. Configures project `archivingproj01` and zone `asia-southeast1-a`.
2. Creates VPC firewall rule `allow-http-https` for Ports 80 & 443.
3. Provisions `datawiz-production-vm` (`e2-standard-2`, 30GB SSD, Ubuntu 22.04 LTS).
4. Fetches the VM's public IP address.
5. SSHes into the VM, downloads `setup-vm.sh`, and runs full system initialization, Next.js build, Alembic migrations, PM2 supervision, and Caddy reverse proxy setup.

---

## Method B: Deployment via GCP Web Console UI (Startup Script)

If you prefer using the graphical Web Console interface to create the VM:

### Step 1: Open Compute Engine Console
1. Go to **[GCP Compute Engine Instances](https://console.cloud.google.com/compute/instances)**.
2. Click **Create Instance**.

### Step 2: Configure VM Settings
- **Name**: `datawiz-production-vm`
- **Region / Zone**: `asia-southeast1` / `asia-southeast1-a`
- **Machine Series / Type**: `E2` / `e2-standard-2` (2 vCPU, 8 GB RAM)
- **Boot Disk**:
  - Operating System: **Ubuntu**
  - Version: **Ubuntu 22.04 LTS**
  - Size: **30 GB** (Standard Persistent Disk)
- **Firewall**:
  - Check **Allow HTTP traffic**
  - Check **Allow HTTPS traffic**

### Step 3: Add Startup Script
1. Scroll down to expand **Advanced options**.
2. Click **Automation**.
3. Under **Startup script**, copy and paste the entire contents of [`startup_script_metadata.sh`](./startup_script_metadata.sh).
4. Click **Create**.

### What Method B Automates
Upon clicking **Create**, Compute Engine boots Ubuntu, runs `startup_script_metadata.sh` automatically as `root`, fetches its public IP dynamically via Google Instance Metadata Server, compiles Next.js, applies DB migrations, configures PM2, and starts Caddy reverse proxy on port 80.

---

## Verification & Monitoring

Once deployment completes:
- **Web Application UI**: `http://<VM_PUBLIC_IP>/`
- **FastAPI API Health Check**: `http://<VM_PUBLIC_IP>/api/health`

### Live Logs & Debugging
To inspect installation progress on Method B:
```bash
# Connect to VM via SSH in GCP Console
sudo tail -f /var/log/datawiz-startup.log
```
