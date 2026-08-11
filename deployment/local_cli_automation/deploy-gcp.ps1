# DataWiz Digital Archive System — Local PowerShell GCP Deployment Orchestrator
# Executes from local Windows PowerShell terminal

$ErrorActionPreference = "Continue"

# Configurable Parameters
$PROJECT_ID = "archivingproj01"
$ZONE = "asia-southeast1-a"
$VM_NAME = "datawiz-production-vm"
$MACHINE_TYPE = "e2-standard-2"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " DataWiz Digital Archive — GCP Production Deployment" -ForegroundColor Cyan
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

Write-Host "[1/6] Using gcloud CLI at: $GCLOUD_CMD" -ForegroundColor Green

# 2. Verify Authentication & Project Configuration
Write-Host "[2/6] Setting GCP Project '$PROJECT_ID' and Zone '$ZONE'..." -ForegroundColor Green
& $GCLOUD_CMD config set project $PROJECT_ID | Out-Null
& $GCLOUD_CMD config set compute/zone $ZONE | Out-Null

# 3. Create VPC Firewall Rule (Expose Ports 80 & 443 Only)
Write-Host "[3/6] Configuring VPC Firewall Rule (Allow HTTP/HTTPS)..." -ForegroundColor Green
& $GCLOUD_CMD compute firewall-rules create allow-http-https `
    --direction=INGRESS `
    --priority=1000 `
    --network=default `
    --action=ALLOW `
    --rules=tcp:80,tcp:443 `
    --source-ranges=0.0.0.0/0 `
    --target-tags=http-server,https-server 2>$null

# 4. Provision Compute Engine VM
Write-Host "[4/6] Provisioning Compute Engine Instance '$VM_NAME' ($MACHINE_TYPE)..." -ForegroundColor Green
& $GCLOUD_CMD compute instances create $VM_NAME `
    --zone=$ZONE `
    --machine-type=$MACHINE_TYPE `
    --image-family=ubuntu-2204-lts `
    --image-project=ubuntu-os-cloud `
    --boot-disk-size=30GB `
    --tags=http-server,https-server 2>$null

# 5. Retrieve VM External Public IP Address
Write-Host "[5/6] Fetching VM External Public IP Address..." -ForegroundColor Green
Start-Sleep -Seconds 5
$VM_IP = (& $GCLOUD_CMD compute instances describe $VM_NAME --zone=$ZONE --format="get(networkInterfaces[0].accessConfigs[0].natIP)").Trim()

if (-not $VM_IP) {
    Write-Error "Failed to retrieve public IP address for VM '$VM_NAME'."
    exit 1
}

Write-Host ">> VM Public External IP: $VM_IP" -ForegroundColor Cyan

# 6. Upload & Execute VM Setup Script
Write-Host "[6/6] Uploading and Executing 'setup-vm.sh' on VM..." -ForegroundColor Green
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SetupScriptPath = Join-Path $ScriptDir "setup-vm.sh"

if (-not (Test-Path $SetupScriptPath)) {
    Write-Error "Could not find setup-vm.sh at '$SetupScriptPath'."
    exit 1
}

# Copy script to remote VM
Write-Host "Uploading setup-vm.sh via SCP..." -ForegroundColor Gray
echo y | & $GCLOUD_CMD compute scp $SetupScriptPath "${VM_NAME}:setup-vm.sh" --zone=$ZONE --quiet

# Execute script remotely via SSH
Write-Host "Running installation script via SSH..." -ForegroundColor Gray
$remoteCmd = "chmod +x setup-vm.sh && bash setup-vm.sh $VM_IP"
echo y | & $GCLOUD_CMD compute ssh $VM_NAME --zone=$ZONE --command=$remoteCmd --quiet

Write-Host "============================================================" -ForegroundColor Green
Write-Host " DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host " Access Application: http://$VM_IP" -ForegroundColor Cyan
Write-Host " Access Backend API: http://$VM_IP/api/health" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Green
