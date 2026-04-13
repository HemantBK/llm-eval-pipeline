"""Tests for circuit breaker pattern."""

import pytest

from app.errors.exceptions import CircuitOpenError
from app.providers.circuit_breaker import CircuitBreaker, CircuitState


class TestCircuitBreaker:
    """Test the circuit breaker state machine."""

    def test_starts_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=10)
        assert cb.state == CircuitState.CLOSED

    def test_stays_closed_on_success(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.on_success()
        cb.on_success()
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.on_failure()
        cb.on_failure()
        assert cb.state == CircuitState.CLOSED  # not yet

        cb.on_failure()  # 3rd failure — trips
        assert cb.state == CircuitState.OPEN

    def test_open_rejects_requests(self):
        cb = CircuitBreaker("test", failure_threshold=2)
        cb.on_failure()
        cb.on_failure()
        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitOpenError):
            cb.check()

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.on_failure()
        cb.on_failure()
        cb.on_success()  # resets
        cb.on_failure()
        cb.on_failure()
        assert cb.state == CircuitState.CLOSED  # not at 3 consecutive

    def test_manual_reset(self):
        cb = CircuitBreaker("test", failure_threshold=2)
        cb.on_failure()
        cb.on_failure()
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        cb.check()  # should not raise

    def test_to_dict(self):
        cb = CircuitBreaker("gemini", failure_threshold=5)
        d = cb.to_dict()
        assert d["provider"] == "gemini"
        assert d["state"] == "closed"
        assert d["failure_count"] == 0
        assert d["failure_threshold"] == 5
