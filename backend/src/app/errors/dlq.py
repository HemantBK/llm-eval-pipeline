"""Dead Letter Queue worker — retries failed evaluations on a schedule.

Nothing is silently lost. Every failed eval lands in the DLQ table and gets
retried with exponential backoff (1min → 5min → 30min). After 3 failures,
it's marked "exhausted" and a Prometheus alert fires for manual review.

This worker runs as a background asyncio task inside the FastAPI process.
"""

import asyncio

import structlog

from app.judge.engine import JudgeEngine
from app.orchestrator import EvalOrchestrator
from app.providers.registry import ProviderRegistry
from app.repositories import EvalRepository

logger = structlog.get_logger()

# How often to check for retryable DLQ items
DLQ_POLL_INTERVAL_S = 60  # every minute


class DLQWorker:
    """
    Background worker that retries failed evaluations from the dead letter queue.

    Lifecycle:
        worker = DLQWorker(session_factory, redis)
        task = asyncio.create_task(worker.run())
        # ... later on shutdown:
        worker.stop()
        await task
    """

    def __init__(self, session_factory, redis) -> None:
        self._session_factory = session_factory
        self._redis = redis
        self._running = False
        self._task: asyncio.Task | None = None

    async def run(self) -> None:
        """Main loop — poll DLQ and retry pending items."""
        self._running = True
        logger.info("DLQ worker started", poll_interval_s=DLQ_POLL_INTERVAL_S)

        while self._running:
            try:
                await self._process_batch()
            except Exception:
                logger.exception("DLQ worker error")

            await asyncio.sleep(DLQ_POLL_INTERVAL_S)

        logger.info("DLQ worker stopped")

    def stop(self) -> None:
        """Signal the worker to stop on the next iteration."""
        self._running = False

    async def _process_batch(self) -> None:
        """Process one batch of retryable DLQ items."""
        async with self._session_factory() as session:
            repo = EvalRepository(session)

            items = await repo.get_retryable_dlq()
            if not items:
                return

            logger.info("DLQ processing batch", count=len(items))

            registry = ProviderRegistry(self._redis)
            judge = JudgeEngine(registry)
            orchestrator = EvalOrchestrator(registry, judge, repo)

            for item in items:
                try:
                    payload = item.payload or {}

                    await orchestrator.evaluate_prompt(
                        prompt_text=item.prompt_text,
                        prompt_id=payload.get("prompt_id", ""),
                        category=payload.get("category", "general"),
                        expected_behavior=payload.get("expected_behavior", ""),
                        models=[item.model_name],
                        rubric_name=payload.get("rubric", "auto"),
                        run_id=item.run_id,
                    )

                    # Success — mark as retried
                    await repo.mark_dlq_retried(item.id)
                    logger.info(
                        "DLQ retry succeeded",
                        dlq_id=str(item.id),
                        model=item.model_name,
                        attempt=item.retry_count + 1,
                    )

                except Exception as e:
                    # Failed again — increment retry count
                    await repo.increment_dlq_retry(item.id)
                    logger.warning(
                        "DLQ retry failed",
                        dlq_id=str(item.id),
                        model=item.model_name,
                        attempt=item.retry_count + 1,
                        error=str(e)[:200],
                    )

            await session.commit()
