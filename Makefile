.PHONY: help up down logs run test lint format migrate clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# --- Docker ---
up: ## Start all services (n8n + FastAPI + Postgres + Redis + vLLM + Prometheus + Grafana)
	docker-compose up -d

down: ## Stop all services
	docker-compose down

logs: ## Tail all service logs
	docker-compose logs -f

logs-api: ## Tail FastAPI logs only
	docker-compose logs -f fastapi

# --- Local Dev ---
run: ## Run FastAPI locally (requires Postgres + Redis running)
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# --- Testing ---
test: ## Run all tests
	cd backend && python -m pytest tests/ -v --tb=short

test-unit: ## Run unit tests only
	cd backend && python -m pytest tests/unit/ -v

test-integration: ## Run integration tests only
	cd backend && python -m pytest tests/integration/ -v

test-cov: ## Run tests with coverage report
	cd backend && python -m pytest tests/ -v --cov=src/app --cov-report=html

load-test: ## Run load tests with Locust (starts web UI at :8089)
	cd backend && locust -f tests/load/locustfile.py --host=http://localhost:8000

# --- Code Quality ---
lint: ## Run linter (ruff + mypy)
	cd backend && ruff check src/ tests/
	cd backend && mypy src/

format: ## Auto-format code
	cd backend && ruff format src/ tests/
	cd backend && ruff check --fix src/ tests/

# --- Database ---
migrate: ## Run Alembic migrations
	cd backend && PYTHONPATH=src alembic upgrade head

migrate-new: ## Create a new migration (usage: make migrate-new msg="add users table")
	cd backend && PYTHONPATH=src alembic revision --autogenerate -m "$(msg)"

# --- Cleanup ---
clean: ## Remove cache files and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf backend/htmlcov
