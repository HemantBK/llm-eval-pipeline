"""Redis response cache — deduplicates identical LLM calls, saves API quota."""

import hashlib
import json

import redis.asyncio as aioredis
import structlog

from app.config import settings
from app.providers.base import LLMResponse

logger = structlog.get_logger()


class ResponseCache:
    """
    Cache LLM responses by (prompt + model + temperature).

    Cache key: sha256(prompt + model_name + str(temperature))
    TTL: 24 hours (configurable via CACHE_TTL_SECONDS)

    Same prompt + same model + same temp = return cached response instantly.
    Saves API quota and money.
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis
        self._ttl = settings.CACHE_TTL_SECONDS
        self._prefix = "llm_cache"

    def _make_key(self, prompt: str, model_name: str, temperature: float) -> str:
        """Generate deterministic cache key from prompt + model + temp."""
        raw = f"{prompt}|{model_name}|{temperature}"
        hash_val = hashlib.sha256(raw.encode()).hexdigest()
        return f"{self._prefix}:{hash_val}"

    async def get(
        self, prompt: str, model_name: str, temperature: float
    ) -> LLMResponse | None:
        """
        Look up a cached response.

        Returns LLMResponse with cached=True if found, None if cache miss.
        """
        key = self._make_key(prompt, model_name, temperature)
        data = await self._redis.get(key)

        if data is None:
            logger.debug("Cache miss", model=model_name, key=key[:20])
            return None

        try:
            cached = json.loads(data)
            logger.info("Cache hit", model=model_name, key=key[:20])
            return LLMResponse(
                text=cached["text"],
                latency_ms=0,  # cached = instant
                token_count=cached.get("token_count", 0),
                model_name=cached["model_name"],
                provider=cached["provider"],
                cached=True,
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Cache parse error, treating as miss", error=str(e))
            await self._redis.delete(key)
            return None

    async def put(
        self,
        prompt: str,
        response: LLMResponse,
        temperature: float,
    ) -> None:
        """Store an LLM response in cache."""
        if response.error:
            return  # never cache errors

        key = self._make_key(prompt, response.model_name, temperature)

        data = json.dumps({
            "text": response.text,
            "token_count": response.token_count,
            "model_name": response.model_name,
            "provider": response.provider,
            "original_latency_ms": response.latency_ms,
        })

        await self._redis.set(key, data, ex=self._ttl)
        logger.debug(
            "Cached response",
            model=response.model_name,
            ttl_h=self._ttl // 3600,
            key=key[:20],
        )

    async def invalidate(
        self, prompt: str, model_name: str, temperature: float
    ) -> None:
        """Remove a specific cache entry."""
        key = self._make_key(prompt, model_name, temperature)
        await self._redis.delete(key)

    async def clear_all(self) -> int:
        """Clear all cached responses. Returns number of keys deleted."""
        pattern = f"{self._prefix}:*"
        keys = []
        async for key in self._redis.scan_iter(match=pattern, count=100):
            keys.append(key)
        if keys:
            await self._redis.delete(*keys)
        logger.info("Cache cleared", keys_deleted=len(keys))
        return len(keys)

    async def stats(self) -> dict:
        """Get cache stats."""
        pattern = f"{self._prefix}:*"
        count = 0
        async for _ in self._redis.scan_iter(match=pattern, count=100):
            count += 1
        return {
            "cached_responses": count,
            "ttl_hours": self._ttl // 3600,
        }
