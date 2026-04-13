"""Google Gemini provider — free tier: 15 RPM, 1M tokens/day."""

import time

import httpx
import structlog

from app.config import settings
from app.errors.exceptions import LLMProviderError, LLMTimeoutError
from app.providers.base import GenerateConfig, LLMProvider, LLMResponse

logger = structlog.get_logger()

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(LLMProvider):
    """Google Gemini API provider."""

    def __init__(self, model: str = "gemini-2.0-flash") -> None:
        self._model = model
        self._client = httpx.AsyncClient(timeout=60.0)

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def default_model(self) -> str:
        return self._model

    async def generate(self, prompt: str, config: GenerateConfig | None = None) -> LLMResponse:
        """Call Gemini API and return standardized response."""
        config = config or GenerateConfig()
        api_key = settings.GEMINI_API_KEY.get_secret_value()

        if not api_key:
            raise LLMProviderError("gemini", 401, "GEMINI_API_KEY not set")

        url = f"{GEMINI_API_BASE}/{self._model}:generateContent?key={api_key}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": config.temperature,
                "maxOutputTokens": config.max_tokens,
            },
        }

        start = time.perf_counter()

        try:
            response = await self._client.post(
                url,
                json=payload,
                timeout=config.timeout_s,
            )
        except httpx.TimeoutException:
            raise LLMTimeoutError("gemini", config.timeout_s)

        latency_ms = int((time.perf_counter() - start) * 1000)

        if response.status_code != 200:
            raise LLMProviderError(
                "gemini",
                response.status_code,
                response.text[:500],
            )

        data = response.json()

        # Extract text from Gemini response format
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise LLMProviderError(
                "gemini",
                200,
                f"Unexpected response format: {str(data)[:300]}",
            )

        # Extract token count if available
        token_count = 0
        usage = data.get("usageMetadata", {})
        token_count = usage.get("candidatesTokenCount", 0) + usage.get("promptTokenCount", 0)

        logger.debug(
            "Gemini response",
            model=self._model,
            latency_ms=latency_ms,
            tokens=token_count,
        )

        return LLMResponse(
            text=text,
            latency_ms=latency_ms,
            token_count=token_count,
            model_name=self._model,
            provider="gemini",
            raw_response=data,
        )
