# Deployment Guide

## Option A: Local Machine (Free)

```bash
docker compose up -d
```

Access at `localhost:5678`, `localhost:8000`, `localhost:3000`.

Best for: development, personal use, demos.

## Option B: Oracle Cloud Free Tier (Free Forever, Recommended)

Oracle provides a free VM with **24GB RAM** — enough for all services including Ollama.

```bash
# 1. Sign up at cloud.oracle.com (free tier, no credit card charge)
# 2. Create VM: Ubuntu 22.04, ARM Ampere, 24GB RAM, 200GB disk
# 3. SSH in:
ssh ubuntu@your-server-ip

# 4. Install Docker
sudo apt update && sudo apt install docker.io docker-compose -y
sudo usermod -aG docker $USER && newgrp docker

# 5. Clone and configure
git clone https://github.com/HemantBK/llm-eval-pipeline.git
cd llm-eval-pipeline
cp .env.example .env
nano .env  # add GEMINI_API_KEY and API_KEY

# 6. Launch
docker compose up -d

# 7. Open firewall
# Oracle Cloud Console → Networking → Virtual Cloud Networks
# → Security List → Add Ingress Rules:
#   Port 5678 (n8n), 8000 (API), 3000 (Grafana)
```

Access: `http://your-server-ip:5678`

## Option C: DigitalOcean / Hetzner ($5-6/month)

Same steps as Oracle on a paid VPS.
- DigitalOcean: $6/month for 1GB RAM
- Hetzner: $5/month for 2GB RAM (better value)

## Option D: Railway / Render (Free Tier)

1. Push to GitHub
2. Connect repo to [Railway](https://railway.app) or [Render](https://render.com)
3. They auto-detect the Dockerfile
4. Add environment variables in their dashboard

## Adding HTTPS

```bash
sudo apt install caddy

# /etc/caddy/Caddyfile
eval-api.yourdomain.com {
    reverse_proxy localhost:8000
}
n8n.yourdomain.com {
    reverse_proxy localhost:5678
}
grafana.yourdomain.com {
    reverse_proxy localhost:3000
}

sudo systemctl restart caddy
```

Caddy auto-provisions Let's Encrypt certificates.

## Sharing with Team

**Option 1: GitHub** — team clones and runs `docker compose up -d`

**Option 2: Deployed instance** — share the server URLs directly

**Option 3: Docker image** — push to GHCR:
```bash
docker build -t ghcr.io/hemantbk/llm-eval-pipeline:latest ./backend
docker push ghcr.io/hemantbk/llm-eval-pipeline:latest
```

## Production Checklist

- [ ] Change default passwords (`N8N_BASIC_AUTH_PASSWORD`, Grafana admin)
- [ ] Set a strong `API_KEY`
- [ ] Enable HTTPS via Caddy or nginx
- [ ] Set `LOG_FORMAT=json` for log aggregation
- [ ] Configure Prometheus alert notification (email/Slack)
- [ ] Set up automated backups for PostgreSQL volume
- [ ] Enable the n8n Schedule Trigger for daily runs
