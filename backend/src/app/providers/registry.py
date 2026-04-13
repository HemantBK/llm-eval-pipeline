"""Provider registry — the single entry point for all LLM calls.

Wraps every provider with: cache → rate limiter → circuit breaker → retry → actual call.
The orchestrator and judge engine ONLY talk to the registry, never to raw providers.
"""

import redis.asyncio as aioredis
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.errors.exceptions import (
    CircuitOpenError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.providers.base import GenerateConfig, LLMProvider, LLMResponse
from app.providers.cache import ResponseCache
from app.providers.circuit_breaker import CircuitBreaker
from app.providers.rate_limiter import RateLimiter

logger = structlog.get_logger()


class ProviderRegistry:
    """
    Central registry for all LLM providers.

    Call flow for every request:
    1. Check Redis cache → return if hit
    2. Check circuit breaker → reject if OPEN
    3. Acquire rate limit slot → wait or reject if over limit
    4. Call provider with tenacity retry (3 attempts, exponential backoff)
    5. On success: cache response, record circuit success
    6. On failure: record circuit failure, maybe send to DLQ
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self._breakers: dict[str, CircuitBreaker] = {}
        self._cache = ResponseCache(redis)
        self._rate_limiter = RateLimiter(
            redis,
            limits={
                "gemini": settings.GEMINI_RPM,
                "openai": settings.OPENAI_RPM,
                "vllm": settings.VLLM_RPM,
                "ollama": 1000,  # local, effectively unlimited
            },
        )

    def register(self, provider: LLMProvider) -> None:
        """Register a provider by its name."""
        self._providers[provider.name] = provider
        self._breakers[provider.name] = CircuitBreaker(
            provider_name=provider.name,
            failure_threshold=5,
            recovery_timeout=60.0,
        )
        logger.info("Registered provider", provider=provider.name, model=provider.default_model)

    def get_provider(self, name: str) -> LLMProvider | None:
        """Get a raw provider by name."""
        return self._providers.get(name)

    @property
    def available_providers(self) -> list[str]:
        """List registered provider names."""
        return list(self._providers.keys())

    async def generate(
        self,
        provider_name: str,
        prompt: str,
        config: GenerateConfig | None = None,
    ) -> LLMResponse:
        """
        Generate a response using the full protection stack:
        cache → circuit breaker → rate limiter → retry → provider call.

        This is the ONLY method the rest of the app should call.
        """
        config = config or GenerateConfig()
        provider = self._providers.get(provider_name)
        if not provider:
            raise LLMProviderError(
                provider_name,
                0,
                f"Unknown provider: {provider_name}. Available: {self.available_providers}",
            )

        from app.metrics import (
            cache_hits_total,
            cache_misses_total,
            circuit_breaker_open,
            circuit_breaker_state,
            circuit_breaker_trips_total,
            llm_call_duration_seconds,
            llm_calls_total,
            llm_errors_total,
            llm_tokens_total,
        )

        # 1. Cache check
        cached = await self._cache.get(prompt, provider.default_model, config.temperature)
        if cached:
            cache_hits_total.labels(provider=provider_name).inc()
            return cached
        cache_misses_total.labels(provider=provider_name).inc()

        # 2. Circuit breaker check
        breaker = self._breakers[provider_name]
        try:
            breaker.check()  # raises CircuitOpenError if OPEN
        except CircuitOpenError:
            llm_errors_total.labels(provider=provider_name, error_type="circuit_open").inc()
            circuit_breaker_open.labels(provider=provider_name).set(1)
            raise

        # Update circuit breaker gauge
        state_map = {"closed": 0, "half_open": 1, "open": 2}
        circuit_breaker_state.labels(provider=provider_name).set(
            state_map.get(breaker.state.value, 0)
        )

        # 3. Rate limit
        await self._rate_limiter.acquire(provider_name, wait=True)

        # 4. Call with retry + metrics
        import time

        start = time.perf_counter()
        try:
            response = await self._call_with_retry(provider, prompt, config)
        except LLMTimeoutError:
            llm_errors_total.labels(
                provider=provider_name,
                error_type="timeout",
            ).inc()
            llm_calls_total.labels(
                provider=provider_name,
                model=provider.default_model,
                status="timeout",
            ).inc()
            breaker.on_failure()
            raise
        except LLMProviderError:
            llm_errors_total.labels(
                provider=provider_name,
                error_type="provider_error",
            ).inc()
            llm_calls_total.labels(
                provider=provider_name,
                model=provider.default_model,
                status="error",
            ).inc()
            breaker.on_failure()
            if breaker.state.value == "open":
                circuit_breaker_trips_total.labels(
                    provider=provider_name,
                ).inc()
                circuit_breaker_open.labels(provider=provider_name).set(1)
            raise
        except Exception:
            llm_errors_total.labels(
                provider=provider_name,
                error_type="unknown",
            ).inc()
            llm_calls_total.labels(
                provider=provider_name,
                model=provider.default_model,
                status="error",
            ).inc()
            breaker.on_failure()
            raise

        duration = time.perf_counter() - start

        # 5. Record success metrics + cache
        model = response.model_name
        llm_calls_total.labels(
            provider=provider_name,
            model=model,
            status="success",
        ).inc()
        llm_call_duration_seconds.labels(
            provider=provider_name,
            model=model,
        ).observe(duration)
        llm_tokens_total.labels(
            provider=provider_name,
            model=model,
        ).inc(response.token_count)
        circuit_breaker_open.labels(provider=provider_name).set(0)

        breaker.on_success()
        await self._cache.put(prompt, response, config.temperature)

        return response

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((LLMProviderError, LLMTimeoutError)),
        reraise=True,
    )
    async def _call_with_retry(
        self,
        provider: LLMProvider,
        prompt: str,
        config: GenerateConfig,
    ) -> LLMResponse:
        """Call provider with tenacity retry — 3 attempts, exponential backoff (1s → 3s → 10s)."""
        return await provider.generate(prompt, config)

    # --- Monitoring ---

    async def get_status(self) -> dict:
        """Get status of all providers for monitoring."""
        status = {}
        for name in self._providers:
            breaker_info = self._breakers[name].to_dict()
            rate_info = await self._rate_limiter.get_usage(name)
            status[name] = {
                **breaker_info,
                "rate_limit": rate_info,
            }
        cache_stats = await self._cache.stats()
        return {
            "providers": status,
            "cache": cache_stats,
        }

    def get_circuit_states(self) -> dict[str, str]:
        """Get circuit breaker states for Prometheus metrics."""
        return {name: breaker.state.value for name, breaker in self._breakers.items()}


def create_registry(redis: aioredis.Redis) -> ProviderRegistry:
    """
    Factory: create a ProviderRegistry with all configured providers.

    Only registers providers that have API keys configured.
    """
    from app.providers.gemini import GeminiProvider
    from app.providers.ollama_provider import OllamaProvider
    from app.providers.openai_provider import OpenAIProvider
    from app.providers.vllm_provider import VLLMProvider

    registry = ProviderRegistry(redis)

    # Always register Gemini (primary, free)
    if settings.GEMINI_API_KEY.get_secret_value():
        registry.register(GeminiProvider())

    # OpenAI (optional)
    if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.get_secret_value():
        registry.register(OpenAIProvider())

    # vLLM (local GPU)
    registry.register(VLLMProvider())

    # Ollama (local CPU fallback)
    registry.register(OllamaProvider())

    logger.info(
        "Provider registry ready",
        providers=registry.available_providers,
    )
    return registry
