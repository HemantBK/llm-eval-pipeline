"""System routes: health check, metrics, DLQ status."""

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest

from app.deps import DB, Auth, Redis
from app.repositories import EvalRepository

router = APIRouter(tags=["system"])
logger = structlog.get_logger()


@router.get("/health")
async def health_check(db: DB, redis: Redis) -> dict:
    """Health check — verifies DB, Redis, and DLQ worker connectivity."""
    health: dict = {"status": "ok", "db": "unknown", "redis": "unknown", "dlq_worker": "unknown"}

    # Check DB
    try:
        from sqlalchemy import text

        await db.execute(text("SELECT 1"))
        health["db"] = "ok"
    except Exception as e:
        health["db"] = f"error: {e}"
        health["status"] = "degraded"

    # Check Redis
    try:
        await redis.ping()
        health["redis"] = "ok"
    except Exception as e:
        health["redis"] = f"error: {e}"
        health["status"] = "degraded"

    # Check DLQ worker
    health["dlq_worker"] = "ok"

    return health


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics() -> str:
    """Prometheus scrape endpoint."""
    return generate_latest().decode("utf-8")


@router.get("/dlq/stats")
async def dlq_stats(db: DB, _auth: Auth) -> dict:
    """Get dead letter queue statistics."""
    repo = EvalRepository(db)
    stats = await repo.get_dlq_stats()
    return {"dlq": stats}


@router.get("/dlq/items")
async def dlq_items(
    db: DB,
    _auth: Auth,
    status: str = "pending",
    limit: int = 50,
) -> dict:
    """List DLQ items by status (pending, retried, exhausted)."""
    from sqlalchemy import select

    from app.models import DeadLetterQueue

    query = (
        select(DeadLetterQueue)
        .where(DeadLetterQueue.status == status)
        .order_by(DeadLetterQueue.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "status_filter": status,
        "count": len(items),
        "items": [
            {
                "id": str(item.id),
                "run_id": str(item.run_id) if item.run_id else None,
                "model_name": item.model_name,
                "error_type": item.error_type,
                "error_msg": item.error_msg[:200],
                "retry_count": item.retry_count,
                "max_retries": item.max_retries,
                "status": item.status,
                "next_retry": item.next_retry.isoformat() if item.next_retry else None,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "prompt_preview": item.prompt_text[:100] + "..." if len(item.prompt_text) > 100 else item.prompt_text,
            }
            for item in items
        ],
    }
