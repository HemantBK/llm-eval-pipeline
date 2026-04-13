"""Tests for structured exception types."""

from app.errors.exceptions import (
    CircuitOpenError,
    EvalPipelineError,
    JudgeParseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    RunResumeError,
)


class TestExceptions:
    def test_provider_error(self):
        e = LLMProviderError("gemini", 500, "Internal Server Error")
        assert e.provider == "gemini"
        assert e.status == 500
        assert "gemini" in str(e)
        assert "500" in str(e)
        assert isinstance(e, EvalPipelineError)

    def test_timeout_error(self):
        e = LLMTimeoutError("openai", 30.0)
        assert e.provider == "openai"
        assert e.timeout_s == 30.0
        assert "30" in str(e)

    def test_rate_limit_error(self):
        e = LLMRateLimitError("gemini", retry_after=45)
        assert e.provider == "gemini"
        assert e.retry_after == 45

    def test_circuit_open_error(self):
        e = CircuitOpenError("vllm")
        assert e.provider == "vllm"
        assert "OPEN" in str(e)

    def test_judge_parse_error(self):
        e = JudgeParseError("raw text here", "Invalid JSON")
        assert e.raw_response == "raw text here"
        assert e.parse_error == "Invalid JSON"

    def test_run_resume_error(self):
        e = RunResumeError("abc-123", "run not found")
        assert e.run_id == "abc-123"

    def test_all_inherit_base(self):
        errors = [
            LLMProviderError("p", 500, "m"),
            LLMTimeoutError("p", 30),
            LLMRateLimitError("p"),
            CircuitOpenError("p"),
            JudgeParseError("r", "e"),
            RunResumeError("id", "reason"),
        ]
        for e in errors:
            assert isinstance(e, EvalPipelineError)
