"""Middleware stack — request ID injection, structured logging, request timing."""

import time
import uuid

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = structlog.get_logger()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Inject a unique request_id into every request.

    - Checks for incoming X-Request-ID header (from n8n or upstream)
    - Generates one if not present
    - Adds it to response headers
    - Binds it to structlog context for all downstream logs
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Get or generate request ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])

        # Bind to structlog context — all logs in this request will include it
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Prometheus metrics
        from app.metrics import (
            http_request_duration_seconds,
            http_requests_in_progress,
            http_requests_total,
        )

        path = request.url.path
        method = request.method

        http_requests_in_progress.inc()
        start = time.perf_counter()

        response = await call_next(request)

        duration_s = time.perf_counter() - start
        duration_ms = int(duration_s * 1000)

        http_requests_in_progress.dec()
        http_requests_total.labels(method=method, path=path, status=response.status_code).inc()
        http_request_duration_seconds.labels(method=method, path=path).observe(duration_s)

        # Add to response headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(duration_ms)

        # Log the request
        logger.info(
            "Request completed",
            method=method,
            path=path,
            status=response.status_code,
            duration_ms=duration_ms,
        )

        return response


class GracefulShutdownMiddleware(BaseHTTPMiddleware):
    """
    Track in-flight requests for graceful shutdown.

    During shutdown, the lifespan handler waits for active requests
    to complete before closing DB/Redis connections.
    """

    def __init__(self, app, **kwargs) -> None:
        super().__init__(app, **kwargs)
        self._active_requests = 0
        self._shutting_down = False

    @property
    def active_requests(self) -> int:
        return self._active_requests

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self._shutting_down:
            return Response(
                content=(
                    '{"error": "server_shutting_down",'
                    ' "detail": "Server is shutting down, please retry"}'
                ),
                status_code=503,
                media_type="application/json",
                headers={"Retry-After": "5"},
            )

        self._active_requests += 1
        try:
            response = await call_next(request)
            return response
        finally:
            self._active_requests -= 1

    def begin_shutdown(self) -> None:
        """Signal that shutdown has begun — reject new requests."""
        self._shutting_down = True


def configure_structlog() -> None:
    """
    Configure structlog for JSON output (production) or colored console (dev).

    Call this once at app startup.
    """
    from app.config import settings

    if settings.LOG_FORMAT == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(structlog, settings.LOG_LEVEL.upper(), structlog.INFO)  # type: ignore
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
