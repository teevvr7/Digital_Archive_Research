#!/usr/bin/env bash
set -euo pipefail

# DataWiz Digital Archive System — GCP Startup Metadata Script
# Automatically executes as root when VM boots up for the first time.
# Designed for use with: gcloud compute instances create --metadata-from-file startup-script=...
# Or pasting into the GCP Web Console UI under Automation -> Startup script.

LOGFILE="/var/log/datawiz-startup.log"
exec > >(tee -a "$LOGFILE") 2>&1

echo "=== [1/8] Starting Automated DataWiz Provisioning ==="

# Get external public IP of the VM dynamically via Google Metadata Server
VM_PUBLIC_IP=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip)
echo "Detected VM Public IP: $VM_PUBLIC_IP"

echo "=== [2/8] Installing Dependencies & System Packages ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update && apt-get upgrade -y
apt-get install -y python3 python3-venv python3-pip git build-essential curl ca-certificates debian-keyring debian-archive-keyring apt-transport-https

# Node.js 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
npm install -g pm2

# Astral uv
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="/root/.local/bin:$PATH"

# Caddy Web Server
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy

# Docker
apt-get install -y docker.io
systemctl enable docker
systemctl start docker

echo "=== [3/8] Starting Isolated Redis Queue Container ==="
if docker ps -a --format '{{.Names}}' | grep -q "^redis-queue$"; then
    docker rm -f redis-queue
fi

docker run -d \
  --name redis-queue \
  --restart always \
  -p 127.0.0.1:6379:6379 \
  redis:alpine

echo "=== [4/8] Fetching Codebase & Writing Environment Files ==="
TARGET_DIR="/opt/Digital_Archive_Research"
if [ ! -d "$TARGET_DIR" ]; then
    git clone https://github.com/teevvr7/Digital_Archive_Research.git "$TARGET_DIR"
fi
cd "$TARGET_DIR"
git fetch origin main
git checkout main
git pull origin main

# Backend .env
cat <<EOF > backend/.env
SUPABASE_URL=https://nyfigvqavhasoarapmtj.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im55ZmlndnFhdmhhc29hcmFwbXRqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA4NjMyNjUsImV4cCI6MjA5NjQzOTI2NX0.oFFicAJj9gUbIkLOq_Ko9wRrv-hBvmn4gCT4pVh-SdA
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im55ZmlndnFhdmhhc29hcmFwbXRqIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MDg2MzI2NSwiZXhwIjoyMDk2NDM5MjY1fQ.GzV9azjaJ0Rxsxn6036YYaMO9WZ3jbMWt-eXu_FlpWI
SUPABASE_JWT_SECRET=EoGa65xnOvZDgdI4KR8ZHIzAMqQkLsi7K+0yBD90UADGXPCcUz0ur5+HJW3gX3+E0n1eG0rJWiAKyghU0aBIFQ==
SUPABASE_STORAGE_BUCKET=documents

DATABASE_URL=postgresql+psycopg://app_user.nyfigvqavhasoarapmtj:elonmuskcol%40bw%21thneym%40r@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres
ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres.nyfigvqavhasoarapmtj:Digital123%40archive@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres
DB_PREPARE_THRESHOLD=none

REDIS_URL=redis://localhost:6379/0
IDP_QUEUE_NAME=idp

VLM_BASE_URL=https://8001-01ktwv34p98sx3n9n7crzkyezh.cloudspaces.litng.ai/v1
VLM_API_KEY=none
VLM_MODEL=qwen3-vl-4b-instruct
PADDLE_OCR_URL=https://8002-01ktwv34p98sx3n9n7crzkyezh.cloudspaces.litng.ai

CONFIDENCE_THRESHOLD=0.7
PROMOTE_AFTER_N=3
VLM_MAX_PAGES=3
MAX_UPLOAD_MB=50

CORS_ALLOW_ORIGINS=http://${VM_PUBLIC_IP},http://localhost:3000,http://127.0.0.1:3000
SENTRY_DSN=
ENV=production
EOF

# Frontend .env.local
cat <<EOF > frontend/.env.local
NEXT_PUBLIC_SUPABASE_URL=https://nyfigvqavhasoarapmtj.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im55ZmlndnFhdmhhc29hcmFwbXRqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA4NjMyNjUsImV4cCI6MjA5NjQzOTI2NX0.oFFicAJj9gUbIkLOq_Ko9wRrv-hBvmn4gCT4pVh-SdA
NEXT_PUBLIC_API_BASE_URL=http://${VM_PUBLIC_IP}/api
EOF

echo "=== [5/8] Backend Virtual Environment & Migrations ==="
cd "$TARGET_DIR/backend"
/root/.local/bin/uv venv venv --python 3.11
source venv/bin/activate
/root/.local/bin/uv pip install -e ".[worker]"
alembic upgrade head

echo "=== [6/8] Compiling Frontend Standalone Bundle ==="
cd "$TARGET_DIR/frontend"
npm install
npm run build

echo "=== [7/8] Configuring Caddy Reverse Proxy ==="
tee /etc/caddy/Caddyfile > /dev/null <<EOF
:80 {
    reverse_proxy /api/* localhost:8000
    reverse_proxy /* localhost:3000
    encode gzip
}
EOF

systemctl restart caddy

echo "=== [8/8] Starting PM2 Process Supervision ==="
cd "$TARGET_DIR"
pm2 delete all || true

pm2 start "venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000" --name datawiz-backend --cwd "$TARGET_DIR/backend"
pm2 start "venv/bin/python -m app.worker" --name datawiz-worker --cwd "$TARGET_DIR/backend"
pm2 start "npm run start -- -p 3000 -H 0.0.0.0" --name datawiz-frontend --cwd "$TARGET_DIR/frontend"

pm2 save
pm2 startup systemd -u root --hp /root || true

echo "=== DataWiz Startup Provisioning Finished ==="
