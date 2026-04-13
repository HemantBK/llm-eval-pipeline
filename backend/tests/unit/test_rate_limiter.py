"""Tests for Redis-backed rate limiter."""

from unittest.mock import AsyncMock

import pytest

from app.errors.exceptions import LLMRateLimitError
from app.providers.rate_limiter import RateLimiter


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    return redis


@pytest.fixture
def limiter(mock_redis):
    return RateLimiter(mock_redis, limits={"gemini": 15, "openai": 60, "vllm": 1000})


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_under_limit(self, limiter, mock_redis):
        mock_redis.incr = AsyncMock(return_value=5)  # 5 out of 15
        result = await limiter.acquire("gemini", wait=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_at_limit(self, limiter, mock_redis):
        mock_redis.incr = AsyncMock(return_value=15)  # exactly at limit
        result = await limiter.acquire("gemini", wait=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_rejects_over_limit_no_wait(self, limiter, mock_redis):
        mock_redis.incr = AsyncMock(return_value=16)  # over limit
        with pytest.raises(LLMRateLimitError):
            await limiter.acquire("gemini", wait=False)

    @pytest.mark.asyncio
    async def test_unknown_provider_uses_default(self, limiter, mock_redis):
        mock_redis.incr = AsyncMock(return_value=500)  # under default 1000
        result = await limiter.acquire("unknown_provider", wait=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_usage(self, limiter, mock_redis):
        mock_redis.get = AsyncMock(return_value="10")
        usage = await limiter.get_usage("gemini")
        assert usage["provider"] == "gemini"
        assert usage["used"] == 10
        assert usage["limit"] == 15
        assert usage["remaining"] == 5
