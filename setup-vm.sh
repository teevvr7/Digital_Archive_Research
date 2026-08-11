#!/usr/bin/env bash
set -euo pipefail

# DataWiz Digital Archive System — Automated VM Initialization Script
# Expected parameter: $1 = VM Public IP address

VM_PUBLIC_IP="${1:-}"

if [ -z "$VM_PUBLIC_IP" ]; then
  echo "Error: VM Public IP address must be passed as the first argument."
  exit 1
fi

echo "=== [1/8] Updating System & Installing OS Packages ==="
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y python3 python3-venv python3-pip git build-essential curl ca-certificates debian-keyring debian-archive-keyring apt-transport-https

echo "=== [2/8] Installing Node.js 20, PM2, Astral uv, and Caddy ==="
# Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo npm install -g pm2

# Astral uv
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Caddy Web Server
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update
sudo apt-get install -y caddy

# Docker
sudo apt-get install -y docker.io
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker $USER || true

echo "=== [3/8] Starting Isolated Redis Queue Container ==="
if sudo docker ps -a --format '{{.Names}}' | grep -q "^redis-queue$"; then
    sudo docker rm -f redis-queue
fi

sudo docker run -d \
  --name redis-queue \
  --restart always \
  -p 127.0.0.1:6379:6379 \
  redis:alpine

echo "=== [4/8] Setting Up Code Repository & Environment Files ==="
cd ~
if [ ! -d "Digital_Archive_Research" ]; then
    git clone https://github.com/teevvr7/Digital_Archive_Research.git
fi
cd Digital_Archive_Research
git fetch origin main
git checkout main
git pull origin main

# Write backend .env
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

# Write frontend .env.local
cat <<EOF > frontend/.env.local
NEXT_PUBLIC_SUPABASE_URL=https://nyfigvqavhasoarapmtj.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im55ZmlndnFhdmhhc29hcmFwbXRqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA4NjMyNjUsImV4cCI6MjA5NjQzOTI2NX0.oFFicAJj9gUbIkLOq_Ko9wRrv-hBvmn4gCT4pVh-SdA
NEXT_PUBLIC_API_BASE_URL=http://${VM_PUBLIC_IP}/api
EOF

echo "=== [5/8] Building Backend & Running Database Migrations ==="
cd ~/Digital_Archive_Research/backend
~/.local/bin/uv venv venv --python 3.11
source venv/bin/activate
~/.local/bin/uv pip install -e ".[worker]"
alembic upgrade head

echo "=== [6/8] Compiling Frontend Standalone Build ==="
cd ~/Digital_Archive_Research/frontend
npm install
npm run build

echo "=== [7/8] Configuring Caddy Reverse Proxy (Port 80) ==="
sudo tee /etc/caddy/Caddyfile > /dev/null <<EOF
:80 {
    reverse_proxy /api/* localhost:8000
    reverse_proxy /* localhost:3000
    encode gzip
}
EOF

sudo systemctl restart caddy

echo "=== [8/8] Starting PM2 Process Supervision ==="
cd ~/Digital_Archive_Research
pm2 delete all || true

pm2 start "venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000" --name datawiz-backend --cwd ~/Digital_Archive_Research/backend
pm2 start "venv/bin/python -m app.worker" --name datawiz-worker --cwd ~/Digital_Archive_Research/backend
pm2 start "npm run start -- -p 3000 -H 0.0.0.0" --name datawiz-frontend --cwd ~/Digital_Archive_Research/frontend

pm2 save

echo "=== [Verification] Healthcheck Results ==="
sleep 3
curl -s http://localhost:8000/api/health || echo "Backend check failed"
curl -I -s http://localhost:3000 | head -n 1 || echo "Frontend check failed"
curl -I -s http://localhost | head -n 1 || echo "Reverse proxy check failed"

echo "=== Deployment Completed Successfully! ==="
