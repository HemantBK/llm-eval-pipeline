# Setup Guide

Complete setup instructions for the LLM Evaluation Pipeline.

## Prerequisites

| Requirement | Version | Check | Install |
|-------------|---------|-------|---------|
| Docker | 20.10+ | `docker --version` | [docker.com](https://docs.docker.com/get-docker/) |
| Docker Compose | 2.0+ | `docker compose version` | Included with Docker Desktop |
| Git | 2.30+ | `git --version` | [git-scm.com](https://git-scm.com/) |

**Optional (GPU acceleration):**

| Requirement | Purpose |
|-------------|---------|
| NVIDIA GPU (CUDA) | Run vLLM at 793 tok/s instead of Ollama at 41 tok/s |
| nvidia-container-toolkit | Docker GPU passthrough |

## API Keys

### Gemini (Required, Free)

1. Go to https://aistudio.google.com/apikey
2. Click **"Create API Key"**
3. Copy the key
4. No credit card needed
5. Free tier: **15 requests/min, 1,000,000 tokens/day**

### OpenAI (Optional)

1. Go to https://platform.openai.com → Sign up
2. Go to **API Keys** → **Create new secret key**
3. $5 free credits (expires in 3 months)
4. Gets you GPT-4o-mini access

### Anthropic (Optional)

1. Go to https://console.anthropic.com → Sign up
2. Phone verify → **API Keys** → **Create key**
3. ~$5 free credits
4. Gets you Claude Haiku access

## Configuration

### Step 1: Clone

```bash
git clone https://github.com/HemantBK/llm-eval-pipeline.git
cd llm-eval-pipeline
```

### Step 2: Create .env

```bash
cp .env.example .env
```

### Step 3: Edit .env

Open `.env` in any editor and set these values:

```env
# REQUIRED
GEMINI_API_KEY=AIzaSy...your-key-here
API_KEY=pick-any-secret-string

# OPTIONAL
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# JUDGE (which LLM scores responses)
JUDGE_PROVIDER=gemini
JUDGE_MODEL=gemini-2.0-flash

# RATE LIMITS (requests per minute)
GEMINI_RPM=15
OPENAI_RPM=60
VLLM_RPM=1000

# CACHE
CACHE_TTL_SECONDS=86400    # 24 hours

# LOGGING
LOG_LEVEL=INFO
LOG_FORMAT=json            # json (production) or console (dev)
```

### Step 4: Launch

```bash
# Without GPU (uses Ollama for local models)
docker compose up -d

# With GPU (uses vLLM — 19x faster)
docker compose --profile gpu up -d
```

### Step 5: Verify

```bash
curl http://localhost:8000/health
# {"status":"ok","db":"ok","redis":"ok","dlq_worker":"ok"}
```

Open:
- http://localhost:8000/docs — API documentation
- http://localhost:5678 — n8n workflow (admin / changeme123)
- http://localhost:3000 — Grafana dashboards (admin / admin)

## n8n Workflow Setup

### Import the Workflow

1. Open http://localhost:5678 → login with `admin` / `changeme123`
2. Go to **Workflows** → **Import from File**
3. Select `n8n/workflows/eval-pipeline.json`
4. Click **Save**

### Connect Google Sheets

1. Click the **"Read Test Prompts"** node in the workflow
2. Click **Create New Credential** → **Google Sheets OAuth2**
3. Follow the Google OAuth popup to allow access
4. Select your Google Sheet and tab
5. Repeat for the **"Write Results to Sheets"** node (select "Results" tab)

**Google Sheet input columns:**
| prompt_id | category | prompt | difficulty | expected_behavior |
|-----------|----------|--------|------------|-------------------|

**Google Sheet output columns (auto-filled):**
| prompt_id | model | overall_pass | accuracy | completeness | code_quality | safety | hallucination | reasoning | latency_ms | cached | timestamp |
|-----------|-------|-------------|----------|-------------|-------------|--------|--------------|-----------|------------|--------|-----------|

### Set API Key in n8n

Go to n8n **Settings** → **Variables** → Add:
- **Name:** `API_KEY`
- **Value:** same as `API_KEY` in your `.env`

### Choose Models

Click the **"Evaluate via FastAPI"** node → edit the JSON body `models` array:

```json
{"models": ["gemini", "vllm"]}     // GPU available
{"models": ["gemini", "ollama"]}   // CPU only
{"models": ["gemini"]}             // Cloud only (simplest)
```

### Test Run

Click **"Manual Trigger"** → **Execute Workflow**. Watch nodes light up green.

### Enable Scheduled Runs

Click **"Daily 9am Schedule"** node → toggle **Enable** → Save.

For full n8n documentation, see [n8n/README.md](https://github.com/HemantBK/llm-eval-pipeline/blob/main/n8n/README.md).

## CPU-Only Mode (No GPU)

If you don't have an NVIDIA GPU:

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
docker compose up -d
```

This replaces vLLM with Ollama. After starting, pull a model:

```bash
docker exec eval-ollama ollama pull llama3.2
```

Then use `"models": ["gemini", "ollama"]` in your eval requests.
