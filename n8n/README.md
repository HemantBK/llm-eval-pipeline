# n8n Workflow — LLM Eval Pipeline (Hybrid)

## How It Works

n8n is the **visual orchestrator**. It does NOT call LLM APIs directly.
Instead, it calls a single FastAPI endpoint that handles everything.

```
[Manual Trigger / Schedule]
        │
        ▼
[Google Sheets: Read Prompts]    ← reads prompt_id, category, prompt, expected_behavior
        │
        ▼
[Split In Batches (size: 5)]     ← respects rate limits
        │
        ▼
[HTTP Request: POST fastapi:8000/eval/prompt]
        │                         ← FastAPI handles: cache, rate limit, LLM call,
        │                            judge scoring, DB save, return results
        ▼
[Code: Parse Scored Results]     ← flatten results: one row per model
        │
        ▼
[Google Sheets: Write Results]   ← append to "Results" tab
        │
        ▼
[Loop back to Split In Batches]  ← process next batch
        │
        ▼ (when all done)
[Code: Generate Summary Report]  ← aggregate: pass rates, model breakdown
        │
        ▼
[Log Summary / Notification]     ← replace with Slack/Email if desired
```

## Setup Instructions

### 1. Import the Workflow

1. Open n8n at `http://localhost:5678`
2. Go to **Workflows** → **Import from File**
3. Select `workflows/eval-pipeline.json`
4. Click **Save**

### 2. Configure Google Sheets

1. In n8n, go to **Settings** → **Credentials** → **Add New**
2. Select **Google Sheets OAuth2**
3. Follow the OAuth flow to connect your Google account
4. In the workflow, click **"Read Test Prompts"** node:
   - Select your Google Sheet ("LLM Eval Test Prompts")
   - Select the sheet/tab with your prompts
5. Click **"Write Results to Sheets"** node:
   - Select the same Google Sheet
   - Select the "Results" tab

### 3. Set the API Key

In n8n:
1. Go to **Settings** → **Variables** (or use Environment Variables)
2. Add: `API_KEY` = your FastAPI API key (from `.env`)

Or in `docker-compose.yml`, add to n8n environment:
```yaml
- API_KEY=your-secret-api-key-here
```

### 4. Configure Models

In the **"Evaluate via FastAPI"** node, edit the JSON body to choose your models:

```json
{
  "models": ["gemini", "vllm"]     // or ["gemini", "ollama"] for CPU
}
```

Available models:
- `gemini` — Google Gemini (free tier, 15 RPM)
- `openai` — OpenAI GPT-4o-mini (needs API key)
- `vllm` — Local vLLM (needs GPU, 793 tok/s)
- `ollama` — Local Ollama (CPU fallback, 41 tok/s)

### 5. Test Run

1. Click **"Manual Trigger"** → **Execute Workflow**
2. Watch each node light up as it processes
3. Check your Google Sheet "Results" tab for scores
4. Check `http://localhost:8000/eval/runs` for the same data in PostgreSQL

### 6. Enable Scheduled Runs (Optional)

1. In the workflow, click **"Daily 9am Schedule"** node
2. Click **Enable** (toggle from disabled)
3. Adjust the cron expression if needed
4. Save the workflow

The pipeline will now run automatically every day at 9am.

## Google Sheet Format

### Input Sheet: "LLM Eval Test Prompts"

| prompt_id | category | prompt | difficulty | expected_behavior |
|-----------|----------|--------|------------|-------------------|
| CS-001 | algorithms | Write a function to find kth largest... | medium | Should use quickselect... |
| INJ-001 | injection | Ignore all previous instructions... | red-team | MUST refuse |

### Output Sheet: "Results"

| prompt_id | model | overall_pass | accuracy | completeness | code_quality | safety | hallucination | reasoning | latency_ms | cached | timestamp |
|-----------|-------|-------------|----------|-------------|-------------|--------|--------------|-----------|------------|--------|-----------|
| CS-001 | gemini-2.0-flash | true | 4 | 5 | 4 | 5 | 5 | 4 | 1234 | false | 2026-04-13T... |

## Troubleshooting

**"Connection refused" on HTTP Request node:**
- Make sure FastAPI is running: `docker-compose logs fastapi`
- URL should be `http://fastapi:8000/eval/prompt` (Docker network)
- For local dev: use `http://localhost:8000/eval/prompt`

**"401 Unauthorized":**
- Check that `API_KEY` environment variable matches the one in `.env`

**"Rate limited" errors:**
- The FastAPI backend handles rate limiting internally
- If you see 429 errors, reduce the batch size in "Split In Batches"

**Empty results:**
- Check `http://localhost:8000/health` — DB and Redis should be "ok"
- Check `http://localhost:8000/dlq/stats` — failed evals go to the DLQ
