# DataWiz Digital Archive System — Automated GCP Deployment Orchestrator
# Executes from local PowerShell

$ErrorActionPreference = "Continue"

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

# 2. Verify Authentication & Project
Write-Host "[2/6] Configuring GCP Project '$PROJECT_ID' and Zone '$ZONE'..." -ForegroundColor Green
& $GCLOUD_CMD config set project $PROJECT_ID
& $GCLOUD_CMD config set compute/zone $ZONE

# 3. Create VPC Firewall Rule (Only HTTP Port 80 & HTTPS Port 443)
Write-Host "[3/6] Configuring Secure VPC Firewall Rules (Ports 80, 443)..." -ForegroundColor Green
& $GCLOUD_CMD compute firewall-rules create allow-http-https `
    --direction=INGRESS `
    --priority=1000 `
    --network=default `
    --action=ALLOW `
    --rules=tcp:80,tcp:443 `
    --source-ranges=0.0.0.0/0 `
    --target-tags=http-server,https-server

# 4. Provision Compute Engine VM
Write-Host "[4/6] Provisioning Compute Engine VM '$VM_NAME' ($MACHINE_TYPE)..." -ForegroundColor Green
& $GCLOUD_CMD compute instances create $VM_NAME `
    --zone=$ZONE `
    --machine-type=$MACHINE_TYPE `
    --image-family=ubuntu-2204-lts `
    --image-project=ubuntu-os-cloud `
    --boot-disk-size=30GB `
    --tags=http-server,https-server

# 5. Fetch VM Public IP Address
Write-Host "[5/6] Retrieving VM External Public IP Address..." -ForegroundColor Green
Start-Sleep -Seconds 5
$VM_IP = (& $GCLOUD_CMD compute instances describe $VM_NAME --zone=$ZONE --format="get(networkInterfaces[0].accessConfigs[0].natIP)").Trim()

if (-not $VM_IP) {
    Write-Error "Failed to retrieve public IP address for VM '$VM_NAME'."
    exit 1
}

Write-Host ">> VM External Public IP: $VM_IP" -ForegroundColor Cyan

# 6. Inject & Execute setup-vm.sh on the VM
Write-Host "[6/6] Injecting and Executing 'setup-vm.sh' on the VM..." -ForegroundColor Green
Write-Host "Uploading setup-vm.sh to VM..." -ForegroundColor Gray
& $GCLOUD_CMD compute scp setup-vm.sh "${VM_NAME}:~/setup-vm.sh" --zone=$ZONE --quiet

Write-Host "Running remote installation script..." -ForegroundColor Gray
$remoteCmd = "chmod +x ~/setup-vm.sh; bash ~/setup-vm.sh $VM_IP"
& $GCLOUD_CMD compute ssh $VM_NAME --zone=$ZONE --command=$remoteCmd --quiet

Write-Host "============================================================" -ForegroundColor Green
Write-Host " DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host " Access Application: http://$VM_IP" -ForegroundColor Cyan
Write-Host " Access Backend API: http://$VM_IP/api/health" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Green
EOF
