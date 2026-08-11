# Domain Name Setup & Free DNS Options Guide

This document provides a comprehensive guide on free and low-cost domain options, low-latency performance evaluation, and step-by-step instructions for attaching a custom domain name with automatic SSL/HTTPS to the deployed **DataWiz Digital Archive System**.

---

## 1. Top Domain & DNS Options Evaluated

### 🏆 Option 1: `is-a.dev` *(Best 100% Free Developer Subdomain)*
* **Format**: `yourname.is-a.dev`
* **How it works**: A community-run open-source registry specifically for developers. You submit a quick Pull Request on GitHub to claim your custom subdomain pointing to your GCP IP (`136.110.21.236`).
* **Pros**: 100% free for life, clean developer domain suffix, supports Cloudflare nameservers and custom `A` records directly. Zero forced ads or forced monthly renewal emails.
* **Cons**: It is a subdomain (`is-a.dev`), not a top-level domain (like `.com`).
* **Link**: [is-a.dev](https://is-a.dev)

---

### 🥈 Option 2: `Dynu` *(Best Managed Free Dynamic DNS)*
* **Format**: `yourname.dynu.net` (or 20+ other domain extensions like `freeddns.org`)
* **How it works**: A high-availability managed Dynamic DNS provider.
* **Pros**: High uptime, global DNS servers, fast lookup resolution, and **no forced monthly active click renewals** (unlike No-IP which expires your domain if you don't click an email every 30 days).
* **Cons**: Free tier is limited to subdomains.
* **Link**: [dynu.com](https://www.dynu.com)

---

### 🎓 Option 3: GitHub Student Developer Pack *(Best Free Top-Level Custom Domain)*
* **Format**: `yourname.me`, `yourname.tech`, `yourname.studio`, or `yourname.live`
* **How it works**: If you have a student email (`.edu` or school email), GitHub provides **1 Year Free Custom TLD** via Namecheap or Name.com.
* **Pros**: Real custom top-level domain, clean and professional.
* **Cons**: Free for the 1st year (renews at ~$10/year after).
* **Link**: [education.github.com/pack](https://education.github.com/pack)

---

### ⚡ Option 4: $1/year Cheap Custom TLD + Free Cloudflare DNS *(Highest Performance & Zero Bottlenecks)*
* **Format**: `yourname.xyz`, `yourname.site`, `yourname.online`
* **How it works**: Buy a $1.00 – $2.00/year domain from Namecheap, Porkbun, or Cloudflare Registrar, and point its DNS to **Cloudflare Free Tier**.
* **Pros**: 
  - **Ultra-Low Latency**: Uses Cloudflare’s global Anycast DNS network (<10ms global DNS lookup).
  - **Enterprise Security**: Includes free DDoS protection, Web Application Firewall (WAF), and HTTP/3 support.
* **Cons**: Costs ~$1 to $2 per year.

---

## ⚠️ Free Providers to Avoid for Production
- **DuckDNS (`duckdns.org`)**: Popular in home-lab setups, but suffers from occasional DDoS outages and higher latency spikes.
- **No-IP**: Forces manual email confirmation every 30 days on the free tier; will deactivate your domain if forgotten.

---

## 2. Step-by-Step Guide: Attaching a Domain to Your GCP System

Because your system is already configured with **Caddy Web Server** on port 80/443, setting up a domain name is **hand-off simple** — Caddy automatically provisions and renews **free Let's Encrypt / ZeroSSL certificates** for HTTPS!

### Step 1: Create an `A Record` pointing to your GCP IP
In your domain dashboard (`is-a.dev`, Dynu, or Cloudflare):
* **Record Type**: `A`
* **Host / Name**: `@` (or `archive`)
* **Value / Points To**: `136.110.21.236` (Your VM's Public IP)
* **TTL**: Auto or `300`

---

### Step 2: Update the Caddyfile on your GCP VM
SSH into your VM:
```bash
gcloud compute ssh datawiz-production-vm --zone=asia-southeast1-a
```

Edit `/etc/caddy/Caddyfile`:
```bash
sudo nano /etc/caddy/Caddyfile
```

Replace `:80` with your domain name (e.g., `archive.yourname.is-a.dev`):
```caddy
archive.yourname.is-a.dev {
    reverse_proxy /api/* localhost:8000
    reverse_proxy /* localhost:3000
    encode gzip
}
```
*(Caddy will automatically fetch an HTTPS SSL certificate for `archive.yourname.is-a.dev` on port 443).*

---

### Step 3: Update Environment Files
Update `backend/.env`:
```env
CORS_ALLOW_ORIGINS=https://archive.yourname.is-a.dev,http://localhost:3000
```

Update `frontend/.env.local`:
```env
NEXT_PUBLIC_API_BASE_URL=https://archive.yourname.is-a.dev/api
```

---

### Step 4: Rebuild Frontend & Restart Services
```bash
cd ~/Digital_Archive_Research/frontend && npm run build
sudo systemctl restart caddy
pm2 restart all
```

Your system will then be live with **secure HTTPS SSL** at `https://archive.yourname.is-a.dev`!
