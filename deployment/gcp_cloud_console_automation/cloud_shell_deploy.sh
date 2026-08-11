#!/usr/bin/env bash
set -euo pipefail

# DataWiz Digital Archive System — GCP Cloud Shell 1-Click Deployment
# Run directly inside Google Cloud Shell (https://shell.cloud.google.com)

PROJECT_ID="archivingproj01"
ZONE="asia-southeast1-a"
VM_NAME="datawiz-production-vm"
MACHINE_TYPE="e2-standard-2"

echo "============================================================"
echo " DataWiz Digital Archive — GCP Cloud Shell Deployment"
echo "============================================================"

# 1. Configure active project & zone
echo "[1/5] Setting GCP Project to '$PROJECT_ID' and Zone to '$ZONE'..."
gcloud config set project "$PROJECT_ID"
gcloud config set compute/zone "$ZONE"

# 2. Create VPC Firewall Rule
echo "[2/5] Creating VPC Firewall Rule (Ports 80, 443)..."
gcloud compute firewall-rules create allow-http-https \
    --direction=INGRESS \
    --priority=1000 \
    --network=default \
    --action=ALLOW \
    --rules=tcp:80,tcp:443 \
    --source-ranges=0.0.0.0/0 \
    --target-tags=http-server,https-server || true

# 3. Create Compute Engine VM
echo "[3/5] Provisioning Compute Engine VM '$VM_NAME' ($MACHINE_TYPE)..."
gcloud compute instances create "$VM_NAME" \
    --zone="$ZONE" \
    --machine-type="$MACHINE_TYPE" \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=30GB \
    --tags=http-server,https-server || true

# 4. Fetch Public IP Address
echo "[4/5] Retrieving VM External Public IP Address..."
sleep 5
VM_IP=$(gcloud compute instances describe "$VM_NAME" --zone="$ZONE" --format="get(networkInterfaces[0].accessConfigs[0].natIP)")

echo ">> VM Public External IP: $VM_IP"

# 5. Inject & Execute setup-vm.sh on remote VM
echo "[5/5] Cloning repository on VM & executing setup-vm.sh..."
gcloud compute ssh "$VM_NAME" --zone="$ZONE" --command="
  curl -sSL https://raw.githubusercontent.com/teevvr7/Digital_Archive_Research/main/deployment/local_cli_automation/setup-vm.sh -o ~/setup-vm.sh
  chmod +x ~/setup-vm.sh
  bash ~/setup-vm.sh $VM_IP
"

echo "============================================================"
echo " DEPLOYMENT COMPLETE!"
echo " Access Application: http://$VM_IP"
echo " Access Backend API: http://$VM_IP/api/health"
echo "============================================================"
