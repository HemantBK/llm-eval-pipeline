"""Redis-backed token bucket rate limiter — per provider, per minute."""

import asyncio
import time

import redis.asyncio as aioredis
import structlog

from app.errors.exceptions import LLMRateLimitError

logger = structlog.get_logger()


class RateLimiter:
    """
    Sliding-window rate limiter backed by Redis.

    Each provider gets its own rate limit (RPM).
    Uses Redis INCR + EXPIRE for atomic counting per minute window.
    """

    def __init__(self, redis: aioredis.Redis, limits: dict[str, int]) -> None:
        """
        Args:
            redis: Redis client
            limits: Provider name → max requests per minute
                    e.g. {"gemini": 15, "openai": 60, "vllm": 1000}
        """
        self._redis = redis
        self._limits = limits

    async def acquire(self, provider: str, wait: bool = True, max_wait_s: float = 30.0) -> bool:
        """
        Acquire a rate limit slot for the given provider.

        Args:
            provider: Provider name (e.g. "gemini")
            wait: If True, wait until a slot is available. If False, raise immediately.
            max_wait_s: Maximum time to wait for a slot.

        Returns:
            True if acquired.

        Raises:
            LLMRateLimitError if limit exceeded and wait=False or max_wait exceeded.
        """
        limit = self._limits.get(provider, 1000)  # default: effectively unlimited
        key = f"ratelimit:{provider}:{int(time.time()) // 60}"  # per-minute window

        start = time.perf_counter()

        while True:
            count = await self._redis.incr(key)

            # Set expiry on first increment (auto-cleanup after 2 minutes)
            if count == 1:
                await self._redis.expire(key, 120)

            if count <= limit:
                logger.debug(
                    "Rate limit acquired",
                    provider=provider,
                    used=count,
                    limit=limit,
                )
                return True

            # Over limit
            if not wait:
                raise LLMRateLimitError(provider, retry_after=60)

            elapsed = time.perf_counter() - start
            if elapsed >= max_wait_s:
                raise LLMRateLimitError(provider, retry_after=int(60 - (time.time() % 60)))

            # Wait until the next minute window
            wait_time = 60 - (time.time() % 60) + 0.1  # wait until next minute + small buffer
            wait_time = min(wait_time, max_wait_s - elapsed)

            logger.info(
                "Rate limited, waiting",
                provider=provider,
                wait_s=round(wait_time, 1),
                used=count,
                limit=limit,
            )
            await asyncio.sleep(wait_time)

    async def get_usage(self, provider: str) -> dict:
        """Get current usage stats for a provider."""
        key = f"ratelimit:{provider}:{int(time.time()) // 60}"
        count = await self._redis.get(key)
        limit = self._limits.get(provider, 1000)
        used = int(count) if count else 0
        return {
            "provider": provider,
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
            "utilization_pct": round((used / limit) * 100, 1) if limit > 0 else 0,
        }
