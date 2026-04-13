# Architecture & Design Decisions

## System Overview

```
n8n (thin orchestrator) → FastAPI (production engine) → LLM Providers
                                    ↕                        ↕
                              PostgreSQL              Redis (cache + rate limit)
                                    ↕
                         Prometheus → Grafana
```

## Why Hybrid (n8n + FastAPI)?

n8n alone cannot handle: caching, circuit breakers, rate limiting, retries with backoff, PostgreSQL, async fan-out, or Prometheus metrics. By making n8n a "thin" orchestrator that calls one FastAPI endpoint, we get **visual workflow for demos** + **production backend for reliability**.

## Why vLLM over Ollama?

vLLM: **793 tok/s** vs Ollama: **41 tok/s** (19x faster). For 50+ prompts across multiple models, this saves hours. Ollama is kept as a CPU fallback.

## Why PostgreSQL over Google Sheets?

Sheets hits API limits at ~100 writes/min, no ACID, no complex queries, no concurrent writes. PostgreSQL handles all of this. We still write to Sheets via n8n for easy viewing.

## Why Redis for Cache AND Rate Limiting?

One instance, two purposes: (1) response cache keyed on `sha256(prompt+model+temp)` saves API quota; (2) token-bucket rate limiter ensures we never exceed provider limits.

## Why a Dead Letter Queue?

A single API timeout shouldn't lose data. Every failed eval is stored with full context and retried with exponential backoff. After 3 failures, a Prometheus alert fires.

## Data Flow

```
POST /eval/prompt
  → Check Redis cache (sha256 key)
    → HIT: return cached response (0ms)
    → MISS: continue
  → Check circuit breaker
    → OPEN: raise CircuitOpenError (503)
    → CLOSED/HALF_OPEN: continue
  → Acquire rate limit slot (Redis token-bucket)
    → OVER LIMIT: wait for next window or reject
  → Call LLM provider (with tenacity retry: 3x, 1s→3s→10s)
    → SUCCESS: continue
    → FAILURE: record circuit failure, maybe DLQ
  → Save raw response to PostgreSQL
  → Call Judge LLM (low temp 0.1, structured JSON output)
    → Parse 6 dimension scores
    → Retry 2x if JSON invalid
  → Save scores to PostgreSQL
  → Cache response in Redis (24h TTL)
  → Return scored JSON
```

## Error Recovery Matrix

| Failure | Detection | Recovery | Time |
|---------|-----------|----------|------|
| LLM 500 | HTTP status | tenacity retry 3x | 1-10s |
| LLM 429 | HTTP status | rate limiter wait | up to 60s |
| Provider down | 5 consecutive failures | circuit breaker OPEN | 60s test |
| Judge bad JSON | JSON parse error | retry with nudge 2x | 5-20s |
| Crash mid-run | run status = "running" | POST /resume | manual |
| Container stop | SIGTERM | 60s graceful drain | 0-60s |
| Exhausted retries | retry_count >= 3 | DLQ → alert | manual |

## 28 Prometheus Metrics

| Category | Metrics |
|----------|---------|
| HTTP | requests_total, duration_seconds (histogram), in_progress |
| LLM | calls_total{provider,status}, duration_seconds, errors_total{type}, tokens_total |
| Cache | hits_total, misses_total, size_total |
| Rate Limit | waits_total, rejections_total, usage_percent{provider} |
| Circuit | state{provider}, open, trips_total |
| Eval | completed_total, passed_total, failed_total, judge_score{dim} |
| Runs | runs_total{status}, duration_seconds, active |
| DLQ | pending_total, retried_total, exhausted_total, added_total |

## Database Schema

```sql
eval_runs → eval_results → judge_scores
                          dead_letter_queue (standalone)
```

4 tables, 12 indexes for fast queries on status, run_id, model, category.
