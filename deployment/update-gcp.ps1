# DataWiz Digital Archive System — Automated GCP VM Update Script
# Executes from local Windows PowerShell terminal

$ErrorActionPreference = "Continue"

# Configurable Parameters
$PROJECT_ID = "archivingproj01"
$ZONE = "asia-southeast1-a"
$VM_NAME = "datawiz-production-vm"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " DataWiz Digital Archive — Updating GCP Production VM" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Locate gcloud CLI executable
$GCLOUD_CMD = Get-Command gcloud -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path

if (-not $GCLOUD_CMD) {
    $PossiblePaths = @(
        "$env:LocalAppData\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
        "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
        "C:\Program Files\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
    )
    foreach ($path in $PossiblePaths) {
        if (Test-Path $path) {
            $GCLOUD_CMD = $path
            break
        }
    }
}

if (-not $GCLOUD_CMD) {
    Write-Error "gcloud CLI was not found. Please complete the Google Cloud SDK installation or restart your shell."
    exit 1
}

Write-Host "[1/3] Using gcloud CLI at: $GCLOUD_CMD" -ForegroundColor Green
& $GCLOUD_CMD config set project $PROJECT_ID | Out-Null
& $GCLOUD_CMD config set compute/zone $ZONE | Out-Null

# 2. Fetch VM External Public IP
Write-Host "[2/3] Fetching VM External Public IP Address..." -ForegroundColor Green
$VM_IP = (& $GCLOUD_CMD compute instances describe $VM_NAME --zone=$ZONE --format="get(networkInterfaces[0].accessConfigs[0].natIP)").Trim()
Write-Host ">> Target VM IP: $VM_IP" -ForegroundColor Cyan

# 3. Pull code, build frontend, restart PM2 services on VM
Write-Host "[3/3] Executing Remote Git Pull, Frontend Build & Service Restart..." -ForegroundColor Green
$remoteCmd = "cd ~/Digital_Archive_Research && git pull origin main && cd frontend && npm run build && pm2 restart all"
echo y | & $GCLOUD_CMD compute ssh $VM_NAME --zone=$ZONE --command=$remoteCmd --quiet

Write-Host "============================================================" -ForegroundColor Green
Write-Host " GCP UPDATE COMPLETE!" -ForegroundColor Green
Write-Host " Access Application: http://$VM_IP" -ForegroundColor Cyan
Write-Host " Access Backend API: http://$VM_IP/api/health" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Green
