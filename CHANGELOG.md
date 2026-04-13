# Changelog

## [0.1.0] - 2026-04-13

### Added
- Hybrid architecture: n8n visual orchestrator + FastAPI production backend
- 4 LLM providers: Gemini, OpenAI, vLLM, Ollama
- LLM-as-Judge scoring engine with 6 dimensions
- 4 built-in rubrics: default, safety, coding, hallucination
- 33 test prompts across coding, injection, harmful, hallucination
- Redis response cache with 24h TTL
- Per-provider rate limiting (token-bucket via Redis)
- Circuit breaker pattern (5 failures → open → 60s recovery)
- Dead letter queue with exponential backoff retry
- Resume from checkpoint for failed runs
- Graceful shutdown (60s drain)
- 28 Prometheus metrics
- Grafana dashboard with 12 panels
- 6 Prometheus alert rules
- PostgreSQL with Alembic migrations
- Docker Compose with 7 services
- n8n workflow with Google Sheets integration
- CI/CD via GitHub Actions
- 50 unit tests
- Locust load test
