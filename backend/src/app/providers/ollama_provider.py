"""Ollama provider — CPU fallback, free forever, no API key needed."""

import time

import httpx
import structlog

from app.config import settings
from app.errors.exceptions import LLMProviderError, LLMTimeoutError
from app.providers.base import GenerateConfig, LLMProvider, LLMResponse

logger = structlog.get_logger()


class OllamaProvider(LLMProvider):
    """
    Ollama provider — runs local models on CPU/GPU.

    Slower than vLLM (~41 tok/s) but works without NVIDIA GPU.
    Good as a fallback when no GPU is available.
    """

    def __init__(self, model: str = "llama3.2") -> None:
        self._model = model
        self._base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self._client = httpx.AsyncClient(timeout=120.0)

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def default_model(self) -> str:
        return self._model

    async def generate(self, prompt: str, config: GenerateConfig | None = None) -> LLMResponse:
        """Call Ollama's /api/generate endpoint."""
        config = config or GenerateConfig()

        url = f"{self._base_url}/api/generate"

        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": config.temperature,
                "num_predict": config.max_tokens,
            },
        }

        start = time.perf_counter()

        try:
            response = await self._client.post(
                url,
                json=payload,
                timeout=config.timeout_s,
            )
        except httpx.ConnectError:
            raise LLMProviderError(
                "ollama",
                0,
                f"Cannot connect to Ollama at {self._base_url}. Is it running?",
            )
        except httpx.TimeoutException:
            raise LLMTimeoutError("ollama", config.timeout_s)

        latency_ms = int((time.perf_counter() - start) * 1000)

        if response.status_code != 200:
            raise LLMProviderError(
                "ollama",
                response.status_code,
                response.text[:500],
            )

        data = response.json()

        text = data.get("response", "")
        if not text:
            raise LLMProviderError(
                "ollama",
                200,
                f"Empty response from Ollama: {str(data)[:300]}",
            )

        # Ollama provides eval_count (tokens generated)
        token_count = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)

        logger.debug(
            "Ollama response",
            model=self._model,
            latency_ms=latency_ms,
            tokens=token_count,
        )

        return LLMResponse(
            text=text,
            latency_ms=latency_ms,
            token_count=token_count,
            model_name=self._model,
            provider="ollama",
            raw_response=data,
        )

    async def health_check(self) -> bool:
        """Check if Ollama is reachable and has the model pulled."""
        try:
            response = await self._client.get(
                f"{self._base_url}/api/tags",
                timeout=5.0,
            )
            if response.status_code != 200:
                return False
            models = [m["name"] for m in response.json().get("models", [])]
            return any(self._model in m for m in models)
        except Exception:
            return False
