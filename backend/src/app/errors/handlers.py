"""FastAPI exception handlers — map structured errors to HTTP responses."""

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.errors.exceptions import (
    CircuitOpenError,
    EvalPipelineError,
    JudgeParseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)

logger = structlog.get_logger()


def register_error_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app."""

    @app.exception_handler(LLMProviderError)
    async def handle_provider_error(request: Request, exc: LLMProviderError) -> JSONResponse:
        logger.error("LLM provider error", provider=exc.provider, status=exc.status)
        return JSONResponse(
            status_code=502,
            content={
                "error": "llm_provider_error",
                "provider": exc.provider,
                "detail": exc.message,
            },
        )

    @app.exception_handler(LLMTimeoutError)
    async def handle_timeout(request: Request, exc: LLMTimeoutError) -> JSONResponse:
        logger.warning("LLM timeout", provider=exc.provider, timeout=exc.timeout_s)
        return JSONResponse(
            status_code=504,
            content={
                "error": "llm_timeout",
                "provider": exc.provider,
                "timeout_s": exc.timeout_s,
            },
        )

    @app.exception_handler(LLMRateLimitError)
    async def handle_rate_limit(request: Request, exc: LLMRateLimitError) -> JSONResponse:
        logger.warning("Rate limited", provider=exc.provider)
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limited",
                "provider": exc.provider,
                "retry_after": exc.retry_after,
            },
            headers={"Retry-After": str(exc.retry_after)},
        )

    @app.exception_handler(CircuitOpenError)
    async def handle_circuit_open(request: Request, exc: CircuitOpenError) -> JSONResponse:
        logger.error("Circuit breaker open", provider=exc.provider)
        return JSONResponse(
            status_code=503,
            content={
                "error": "circuit_open",
                "provider": exc.provider,
                "detail": "Provider is temporarily unavailable",
            },
        )

    @app.exception_handler(JudgeParseError)
    async def handle_judge_parse(request: Request, exc: JudgeParseError) -> JSONResponse:
        logger.error("Judge parse error", parse_error=exc.parse_error)
        return JSONResponse(
            status_code=502,
            content={
                "error": "judge_parse_error",
                "detail": exc.parse_error,
            },
        )

    @app.exception_handler(EvalPipelineError)
    async def handle_pipeline_error(request: Request, exc: EvalPipelineError) -> JSONResponse:
        logger.error("Pipeline error", error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": "pipeline_error", "detail": str(exc)},
        )
