"""Tests for Redis response cache — key generation, hit/miss, TTL."""

import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from app.providers.base import LLMResponse
from app.providers.cache import ResponseCache


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.scan_iter = AsyncMock(return_value=iter([]))
    return redis


@pytest.fixture
def cache(mock_redis):
    return ResponseCache(mock_redis)


class TestCacheKeyGeneration:
    """Test deterministic cache key generation."""

    def test_same_input_same_key(self, cache):
        k1 = cache._make_key("hello", "model-a", 0.7)
        k2 = cache._make_key("hello", "model-a", 0.7)
        assert k1 == k2

    def test_different_prompt_different_key(self, cache):
        k1 = cache._make_key("hello", "model-a", 0.7)
        k2 = cache._make_key("world", "model-a", 0.7)
        assert k1 != k2

    def test_different_model_different_key(self, cache):
        k1 = cache._make_key("hello", "model-a", 0.7)
        k2 = cache._make_key("hello", "model-b", 0.7)
        assert k1 != k2

    def test_different_temp_different_key(self, cache):
        k1 = cache._make_key("hello", "model-a", 0.7)
        k2 = cache._make_key("hello", "model-a", 0.3)
        assert k1 != k2

    def test_key_has_prefix(self, cache):
        key = cache._make_key("test", "model", 0.5)
        assert key.startswith("llm_cache:")


class TestCacheMiss:
    """Test cache miss behavior."""

    @pytest.mark.asyncio
    async def test_returns_none_on_miss(self, cache):
        result = await cache.get("prompt", "model", 0.7)
        assert result is None


class TestCacheHit:
    """Test cache hit behavior."""

    @pytest.mark.asyncio
    async def test_returns_response_on_hit(self, cache, mock_redis):
        cached_data = json.dumps({
            "text": "cached response",
            "token_count": 42,
            "model_name": "gemini-2.0-flash",
            "provider": "gemini",
            "original_latency_ms": 500,
        })
        mock_redis.get = AsyncMock(return_value=cached_data)

        result = await cache.get("prompt", "gemini-2.0-flash", 0.7)

        assert result is not None
        assert result.text == "cached response"
        assert result.cached is True
        assert result.latency_ms == 0  # cached = instant
        assert result.provider == "gemini"


class TestCachePut:
    """Test storing responses in cache."""

    @pytest.mark.asyncio
    async def test_stores_response(self, cache, mock_redis):
        response = LLMResponse(
            text="test response",
            latency_ms=200,
            token_count=30,
            model_name="model",
            provider="test",
        )

        await cache.put("prompt", response, 0.7)
        mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_cache_errors(self, cache, mock_redis):
        response = LLMResponse(
            text="error",
            latency_ms=0,
            token_count=0,
            model_name="model",
            provider="test",
            error="something went wrong",
        )

        await cache.put("prompt", response, 0.7)
        mock_redis.set.assert_not_called()
