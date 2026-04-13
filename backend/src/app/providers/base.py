"""Abstract base class for all LLM providers + shared dataclasses."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class GenerateConfig:
    """Configuration for an LLM generation request."""

    temperature: float = 0.7
    max_tokens: int = 2048
    timeout_s: float = 30.0
    stream: bool = False


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""

    text: str
    latency_ms: int
    token_count: int
    model_name: str
    provider: str
    cached: bool = False
    error: str | None = None
    raw_response: dict = field(default_factory=dict)


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    Every provider (Gemini, OpenAI, vLLM, Ollama) implements this interface.
    The orchestrator calls providers through this abstraction — it never
    knows or cares which provider is behind it.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name: 'gemini', 'openai', 'vllm', 'ollama'."""
        ...

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model name for this provider."""
        ...

    @abstractmethod
    async def generate(self, prompt: str, config: GenerateConfig | None = None) -> LLMResponse:
        """
        Send a prompt to the LLM and return a standardized response.

        This is the ONLY method subclasses need to implement.
        Retries, circuit breaker, caching, and rate limiting are handled
        by the wrapping layers (see registry.py).
        """
        ...

    async def health_check(self) -> bool:
        """Check if the provider is reachable. Default: try a tiny generation."""
        try:
            response = await self.generate(
                "Say 'ok'.",
                GenerateConfig(max_tokens=5, timeout_s=10.0),
            )
            return bool(response.text)
        except Exception:
            return False
