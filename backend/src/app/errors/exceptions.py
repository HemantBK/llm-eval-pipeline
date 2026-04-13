"""Structured exception types for the evaluation pipeline."""


class EvalPipelineError(Exception):
    """Base error for all pipeline errors."""


class LLMProviderError(EvalPipelineError):
    """LLM API returned an error (4xx/5xx)."""

    def __init__(self, provider: str, status: int, message: str) -> None:
        self.provider = provider
        self.status = status
        self.message = message
        super().__init__(f"[{provider}] HTTP {status}: {message}")


class LLMTimeoutError(EvalPipelineError):
    """LLM call exceeded timeout."""

    def __init__(self, provider: str, timeout_s: float) -> None:
        self.provider = provider
        self.timeout_s = timeout_s
        super().__init__(f"[{provider}] Timeout after {timeout_s}s")


class LLMRateLimitError(EvalPipelineError):
    """Rate limit exceeded for provider."""

    def __init__(self, provider: str, retry_after: int = 60) -> None:
        self.provider = provider
        self.retry_after = retry_after
        super().__init__(f"[{provider}] Rate limited, retry after {retry_after}s")


class CircuitOpenError(EvalPipelineError):
    """Provider circuit breaker is open (too many failures)."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"[{provider}] Circuit breaker OPEN — provider is down")


class JudgeParseError(EvalPipelineError):
    """Judge LLM returned unparseable response."""

    def __init__(self, raw_response: str, parse_error: str) -> None:
        self.raw_response = raw_response
        self.parse_error = parse_error
        super().__init__(f"Judge parse error: {parse_error}")


class RunResumeError(EvalPipelineError):
    """Failed to resume a partial run."""

    def __init__(self, run_id: str, reason: str) -> None:
        self.run_id = run_id
        self.reason = reason
        super().__init__(f"Cannot resume run {run_id}: {reason}")
