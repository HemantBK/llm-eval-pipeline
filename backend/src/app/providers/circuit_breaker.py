"""Circuit breaker pattern — stops calling a provider after repeated failures."""

import time
from enum import Enum

import structlog

from app.errors.exceptions import CircuitOpenError

logger = structlog.get_logger()


class CircuitState(Enum):
    CLOSED = "closed"  # Normal — requests flow through
    OPEN = "open"  # Broken — all requests rejected immediately
    HALF_OPEN = "half_open"  # Testing — allow ONE request to test recovery


class CircuitBreaker:
    """
    Circuit breaker for LLM providers.

    CLOSED → after `failure_threshold` consecutive failures → OPEN
    OPEN   → after `recovery_timeout` seconds → HALF_OPEN
    HALF_OPEN → if test request succeeds → CLOSED
               if test request fails → OPEN (reset timer)

    Prevents hammering a downed provider and wasting time on guaranteed failures.
    """

    def __init__(
        self,
        provider_name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        self.provider_name = provider_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._success_count = 0

    @property
    def state(self) -> CircuitState:
        """Current circuit state, with automatic OPEN → HALF_OPEN transition."""
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                logger.info(
                    "Circuit half-open, testing recovery",
                    provider=self.provider_name,
                    elapsed_s=round(elapsed, 1),
                )
                self._state = CircuitState.HALF_OPEN
        return self._state

    def check(self) -> None:
        """
        Check if request is allowed through the circuit.

        Raises CircuitOpenError if circuit is OPEN.
        """
        current_state = self.state  # triggers auto OPEN→HALF_OPEN check

        if current_state == CircuitState.OPEN:
            raise CircuitOpenError(self.provider_name)

        # HALF_OPEN: allow one request through (the test)
        # CLOSED: allow all requests through

    def on_success(self) -> None:
        """Record a successful call — resets failure count."""
        previous = self._state

        self._failure_count = 0
        self._state = CircuitState.CLOSED
        self._success_count += 1

        if previous != CircuitState.CLOSED:
            logger.info(
                "Circuit closed — provider recovered",
                provider=self.provider_name,
                previous_state=previous.value,
            )

    def on_failure(self) -> None:
        """Record a failed call — may trip the circuit."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # Test request failed — back to OPEN
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit re-opened — recovery test failed",
                provider=self.provider_name,
            )

        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.error(
                "Circuit OPENED — too many failures",
                provider=self.provider_name,
                failures=self._failure_count,
                threshold=self.failure_threshold,
                recovery_in_s=self.recovery_timeout,
            )

    def reset(self) -> None:
        """Manually reset the circuit to CLOSED."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        logger.info("Circuit manually reset", provider=self.provider_name)

    def to_dict(self) -> dict:
        """Export state for monitoring/metrics."""
        return {
            "provider": self.provider_name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_s": self.recovery_timeout,
            "total_successes": self._success_count,
        }
