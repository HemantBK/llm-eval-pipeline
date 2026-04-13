"""vLLM provider — local, GPU-accelerated, OpenAI-compatible API. 793 tok/s (19x faster than Ollama)."""

import time

import httpx
import structlog

from app.config import settings
from app.errors.exceptions import LLMProviderError, LLMTimeoutError
from app.providers.base import GenerateConfig, LLMProvider, LLMResponse

logger = structlog.get_logger()


class VLLMProvider(LLMProvider):
    """
    vLLM provider — uses OpenAI-compatible /v1/chat/completions endpoint.

    vLLM serves local models at ~793 tok/s with PagedAttention.
    Docker: vllm/vllm-openai:latest
    """

    def __init__(self, model: str = "meta-llama/Llama-3.2-3B-Instruct") -> None:
        self._model = model
        self._base_url = settings.VLLM_BASE_URL.rstrip("/")
        self._client = httpx.AsyncClient(timeout=120.0)

    @property
    def name(self) -> str:
        return "vllm"

    @property
    def default_model(self) -> str:
        return self._model

    async def generate(self, prompt: str, config: GenerateConfig | None = None) -> LLMResponse:
        """Call vLLM's OpenAI-compatible chat completions endpoint."""
        config = config or GenerateConfig()

        url = f"{self._base_url}/chat/completions"

        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "stream": False,
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
                "vllm",
                0,
                f"Cannot connect to vLLM at {self._base_url}. Is it running?",
            )
        except httpx.TimeoutException:
            raise LLMTimeoutError("vllm", config.timeout_s)

        latency_ms = int((time.perf_counter() - start) * 1000)

        if response.status_code != 200:
            raise LLMProviderError(
                "vllm",
                response.status_code,
                response.text[:500],
            )

        data = response.json()

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            raise LLMProviderError(
                "vllm",
                200,
                f"Unexpected response format: {str(data)[:300]}",
            )

        token_count = data.get("usage", {}).get("total_tokens", 0)

        logger.debug(
            "vLLM response",
            model=self._model,
            latency_ms=latency_ms,
            tokens=token_count,
        )

        return LLMResponse(
            text=text,
            latency_ms=latency_ms,
            token_count=token_count,
            model_name=self._model,
            provider="vllm",
            raw_response=data,
        )

    async def health_check(self) -> bool:
        """Check if vLLM server is reachable."""
        try:
            response = await self._client.get(
                f"{self._base_url}/models",
                timeout=5.0,
            )
            return response.status_code == 200
        except Exception:
            return False
