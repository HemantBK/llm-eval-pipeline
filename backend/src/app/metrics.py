"""Prometheus metrics — every important signal in one place.

These metrics feed into Grafana dashboards and Prometheus alerts.
Import and use from anywhere in the codebase.
"""

from prometheus_client import Counter, Gauge, Histogram, Info

# ============================================================================
# Application Info
# ============================================================================
app_info = Info(
    "eval_pipeline",
    "LLM Eval Pipeline application info",
)
app_info.info(
    {
        "version": "0.1.0",
        "judge_default": "gemini",
    }
)

# ============================================================================
# HTTP Request Metrics (FastAPI middleware)
# ============================================================================
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)

http_requests_in_progress = Gauge(
    "http_requests_in_progress",
    "Number of HTTP requests currently being processed",
)

# ============================================================================
# LLM Provider Metrics
# ============================================================================
llm_calls_total = Counter(
    "llm_calls_total",
    "Total LLM API calls",
    ["provider", "model", "status"],  # status: success, error, timeout, rate_limited
)

llm_call_duration_seconds = Histogram(
    "llm_call_duration_seconds",
    "LLM API call latency in seconds",
    ["provider", "model"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0],
)

llm_errors_total = Counter(
    "llm_errors_total",
    "Total LLM errors by provider and type",
    ["provider", "error_type"],  # error_type: timeout, rate_limit, provider_error, circuit_open
)

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total tokens consumed across LLM calls",
    ["provider", "model"],
)

# ============================================================================
# Cache Metrics
# ============================================================================
cache_hits_total = Counter(
    "cache_hits_total",
    "Cache hit count",
    ["provider"],
)

cache_misses_total = Counter(
    "cache_misses_total",
    "Cache miss count",
    ["provider"],
)

cache_size = Gauge(
    "cache_size_total",
    "Number of cached responses",
)

# ============================================================================
# Rate Limiter Metrics
# ============================================================================
rate_limit_waits_total = Counter(
    "rate_limit_waits_total",
    "Number of times a request had to wait for rate limit",
    ["provider"],
)

rate_limit_rejections_total = Counter(
    "rate_limit_rejections_total",
    "Number of rate limit rejections",
    ["provider"],
)

rate_limit_usage_percent = Gauge(
    "rate_limit_usage_percent",
    "Current rate limit utilization percentage",
    ["provider"],
)

# ============================================================================
# Circuit Breaker Metrics
# ============================================================================
circuit_breaker_state = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state: 0=closed, 1=half_open, 2=open",
    ["provider"],
)

circuit_breaker_open = Gauge(
    "circuit_breaker_open",
    "1 if circuit breaker is open for this provider, 0 otherwise",
    ["provider"],
)

circuit_breaker_trips_total = Counter(
    "circuit_breaker_trips_total",
    "Number of times the circuit breaker tripped open",
    ["provider"],
)

# ============================================================================
# Judge / Evaluation Metrics
# ============================================================================
eval_completed_total = Counter(
    "eval_completed_total",
    "Total evaluations completed",
    ["provider", "category"],
)

eval_passed_total = Counter(
    "eval_passed_total",
    "Total evaluations that passed",
    ["provider", "category"],
)

eval_failed_total = Counter(
    "eval_failed_total",
    "Total evaluations that failed",
    ["provider", "category"],
)

judge_call_duration_seconds = Histogram(
    "judge_call_duration_seconds",
    "Judge LLM call latency in seconds",
    ["judge_model"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 45.0],
)

judge_score = Histogram(
    "judge_score",
    "Distribution of judge scores by dimension",
    ["dimension", "category"],
    buckets=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
)

judge_parse_failures_total = Counter(
    "judge_parse_failures_total",
    "Number of times judge response could not be parsed",
    ["judge_model"],
)

# ============================================================================
# Eval Run Metrics
# ============================================================================
eval_runs_total = Counter(
    "eval_runs_total",
    "Total evaluation runs created",
    ["status"],  # completed, failed, timed_out
)

eval_run_duration_seconds = Histogram(
    "eval_run_duration_seconds",
    "Total duration of evaluation runs",
    buckets=[10, 30, 60, 120, 300, 600, 1200, 1800],
)

eval_runs_active = Gauge(
    "eval_runs_active",
    "Number of currently running evaluation runs",
)

# ============================================================================
# Dead Letter Queue Metrics
# ============================================================================
dlq_pending_total = Gauge(
    "dlq_pending_total",
    "Number of pending items in the dead letter queue",
)

dlq_retried_total = Counter(
    "dlq_retried_total",
    "Total DLQ items successfully retried",
)

dlq_exhausted_total = Counter(
    "dlq_exhausted_total",
    "Total DLQ items that exhausted all retries",
)

dlq_added_total = Counter(
    "dlq_added_total",
    "Total items added to the dead letter queue",
    ["error_type", "provider"],
)
