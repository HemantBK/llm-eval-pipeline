"""Application configuration loaded from environment variables."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All config loaded from .env or environment variables. No hardcoded secrets."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://eval:eval_dev@localhost:5432/eval_pipeline"

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- API Auth ---
    API_KEY: SecretStr = SecretStr("dev-api-key-change-me")

    # --- LLM Provider Keys ---
    GEMINI_API_KEY: SecretStr = SecretStr("")
    OPENAI_API_KEY: SecretStr | None = None
    ANTHROPIC_API_KEY: SecretStr | None = None

    # --- vLLM / Ollama ---
    VLLM_BASE_URL: str = "http://localhost:8001/v1"
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # --- Judge ---
    JUDGE_PROVIDER: str = "gemini"  # "gemini", "vllm", "ollama", "openai"
    JUDGE_MODEL: str = "gemini-2.0-flash"

    # --- Rate Limits (requests per minute) ---
    GEMINI_RPM: int = 15
    OPENAI_RPM: int = 60
    VLLM_RPM: int = 1000  # local, effectively unlimited

    # --- Cache ---
    CACHE_TTL_SECONDS: int = 86400  # 24 hours

    # --- Observability ---
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # "json" or "console"

    # --- Server ---
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1


settings = Settings()
