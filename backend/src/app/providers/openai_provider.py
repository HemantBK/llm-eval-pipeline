"""OpenAI provider — optional, uses $5 free credits."""

import time

import httpx
import structlog

from app.config import settings
from app.errors.exceptions import LLMProviderError, LLMTimeoutError
from app.providers.base import GenerateConfig, LLMProvider, LLMResponse

logger = structlog.get_logger()

OPENAI_API_BASE = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(LLMProvider):
    """OpenAI API provider (GPT-4o-mini, etc.)."""

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self._model = model
        self._client = httpx.AsyncClient(timeout=60.0)

    @property
    def name(self) -> str:
        return "openai"

    @property
    def default_model(self) -> str:
        return self._model

    async def generate(self, prompt: str, config: GenerateConfig | None = None) -> LLMResponse:
        """Call OpenAI Chat Completions API."""
        config = config or GenerateConfig()

        api_key = settings.OPENAI_API_KEY
        if not api_key:
            raise LLMProviderError("openai", 401, "OPENAI_API_KEY not set")

        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

        start = time.perf_counter()

        try:
            response = await self._client.post(
                OPENAI_API_BASE,
                json=payload,
                headers=headers,
                timeout=config.timeout_s,
            )
        except httpx.TimeoutException:
            raise LLMTimeoutError("openai", config.timeout_s)

        latency_ms = int((time.perf_counter() - start) * 1000)

        if response.status_code != 200:
            raise LLMProviderError(
                "openai",
                response.status_code,
                response.text[:500],
            )

        data = response.json()

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            raise LLMProviderError(
                "openai",
                200,
                f"Unexpected response format: {str(data)[:300]}",
            )

        token_count = 0
        usage = data.get("usage", {})
        token_count = usage.get("total_tokens", 0)

        logger.debug(
            "OpenAI response",
            model=self._model,
            latency_ms=latency_ms,
            tokens=token_count,
        )

        return LLMResponse(
            text=text,
            latency_ms=latency_ms,
            token_count=token_count,
            model_name=self._model,
            provider="openai",
            raw_response=data,
        )
