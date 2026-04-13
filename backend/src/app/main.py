"""FastAPI application factory with lifespan management, middleware, and DLQ worker."""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

logger = structlog.get_logger()

# Global references for graceful shutdown
_dlq_task: asyncio.Task | None = None
_shutdown_middleware = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle: startup, DLQ worker, and graceful shutdown."""
    global _dlq_task

    # --- Configure structured logging ---
    from app.middleware import configure_structlog

    configure_structlog()

    # --- Startup ---
    logger.info("Starting LLM Eval Pipeline", version="0.1.0")

    # Initialize database connection pool + Redis
    from app.deps import init_db, init_redis

    await init_db()
    await init_redis()

    # Verify provider registry
    from app.deps import get_redis

    try:
        redis = await get_redis()
        from app.providers.registry import create_registry

        registry = create_registry(redis)
        providers = registry.available_providers
    except Exception:
        providers = ["(registry init deferred)"]

    # Start DLQ background worker
    from app.deps import _session_factory
    from app.errors.dlq import DLQWorker

    try:
        redis = await get_redis()
        dlq_worker = DLQWorker(_session_factory, redis)
        _dlq_task = asyncio.create_task(dlq_worker.run())
        app.state.dlq_worker = dlq_worker
        dlq_status = "running"
    except Exception as e:
        dlq_status = f"failed: {e}"
        logger.warning("DLQ worker failed to start", error=str(e))

    logger.info(
        "Services initialized",
        database="connected",
        redis="connected",
        judge_provider=settings.JUDGE_PROVIDER,
        providers=providers,
        dlq_worker=dlq_status,
    )

    yield

    # --- Shutdown ---
    logger.info("Shutting down — draining in-flight requests...")

    # 1. Signal middleware to reject new requests
    if _shutdown_middleware:
        _shutdown_middleware.begin_shutdown()
        # Wait briefly for in-flight requests to complete
        for _ in range(60):  # max 60 seconds
            if _shutdown_middleware.active_requests == 0:
                break
            logger.info(
                "Waiting for in-flight requests",
                active=_shutdown_middleware.active_requests,
            )
            await asyncio.sleep(1)

    # 2. Stop DLQ worker
    if hasattr(app.state, "dlq_worker"):
        app.state.dlq_worker.stop()
    if _dlq_task and not _dlq_task.done():
        _dlq_task.cancel()
        try:
            await _dlq_task
        except asyncio.CancelledError:
            pass
    logger.info("DLQ worker stopped")

    # 3. Close connections
    from app.deps import close_db, close_redis

    await close_db()
    await close_redis()

    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    global _shutdown_middleware

    app = FastAPI(
        title="LLM Eval Pipeline",
        description="Production-grade LLM Evaluation & Red-Teaming Pipeline",
        version="0.1.0",
        lifespan=lifespan,
    )

    # --- Middleware (order matters: outermost first) ---

    # CORS — allow n8n and local dev
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request ID injection + structured logging
    from app.middleware import GracefulShutdownMiddleware, RequestIDMiddleware

    app.add_middleware(RequestIDMiddleware)

    _shutdown_middleware = GracefulShutdownMiddleware(app)
    # Note: GracefulShutdownMiddleware is instantiated but added manually
    # because Starlette middleware ordering is LIFO. We add it via app state
    # so the lifespan handler can access it.
    app.state.shutdown_middleware = _shutdown_middleware

    # --- Register Routes ---
    from app.routes.eval import router as eval_router
    from app.routes.system import router as system_router

    app.include_router(system_router)
    app.include_router(eval_router, prefix="/eval", tags=["evaluation"])

    # --- Register Error Handlers ---
    from app.errors.handlers import register_error_handlers

    register_error_handlers(app)

    return app


app = create_app()
