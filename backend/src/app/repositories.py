"""Async CRUD repositories for all database operations."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Sequence

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeadLetterQueue, EvalResult, EvalRun, JudgeScore

logger = structlog.get_logger()


class EvalRepository:
    """All database operations for evaluation runs, results, and scores."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # === Eval Runs ===

    async def create_run(
        self,
        name: str,
        config: dict | None = None,
        prompt_count: int = 0,
    ) -> EvalRun:
        """Create a new evaluation run."""
        run = EvalRun(
            name=name,
            status="pending",
            config=config,
            prompt_count=prompt_count,
        )
        self.session.add(run)
        await self.session.flush()
        logger.info("Created eval run", run_id=str(run.id), name=name)
        return run

    async def get_run(self, run_id: uuid.UUID) -> EvalRun | None:
        """Get an evaluation run by ID."""
        return await self.session.get(EvalRun, run_id)

    async def update_run_status(
        self,
        run_id: uuid.UUID,
        status: str,
        pass_rate: float | None = None,
    ) -> None:
        """Update run status and optionally pass rate."""
        values: dict = {"status": status}
        if status in ("completed", "failed", "timed_out"):
            values["completed_at"] = func.now()
        if pass_rate is not None:
            values["pass_rate"] = pass_rate
        await self.session.execute(
            update(EvalRun).where(EvalRun.id == run_id).values(**values)
        )

    async def list_runs(
        self, limit: int = 50, offset: int = 0
    ) -> Sequence[EvalRun]:
        """List evaluation runs, most recent first."""
        result = await self.session.execute(
            select(EvalRun)
            .order_by(EvalRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    # === Eval Results ===

    async def save_result(
        self,
        run_id: uuid.UUID,
        prompt_id: str,
        prompt_text: str,
        category: str,
        expected_behavior: str,
        model_name: str,
        provider: str,
        raw_response: str | None = None,
        latency_ms: int = 0,
        token_count: int = 0,
        cached: bool = False,
        error: str | None = None,
        overall_pass: bool | None = None,
    ) -> EvalResult:
        """Save an LLM response result."""
        result = EvalResult(
            run_id=run_id,
            prompt_id=prompt_id,
            prompt_text=prompt_text,
            category=category,
            expected_behavior=expected_behavior,
            model_name=model_name,
            provider=provider,
            raw_response=raw_response,
            latency_ms=latency_ms,
            token_count=token_count,
            cached=cached,
            error=error,
            overall_pass=overall_pass,
        )
        self.session.add(result)
        await self.session.flush()
        return result

    async def get_results_for_run(
        self,
        run_id: uuid.UUID,
        model: str | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[EvalResult], int]:
        """Get paginated results for a run with optional filters. Returns (results, total_count)."""
        query = select(EvalResult).where(EvalResult.run_id == run_id)
        count_query = select(func.count()).select_from(EvalResult).where(EvalResult.run_id == run_id)

        if model:
            query = query.where(EvalResult.model_name == model)
            count_query = count_query.where(EvalResult.model_name == model)
        if category:
            query = query.where(EvalResult.category == category)
            count_query = count_query.where(EvalResult.category == category)

        query = query.order_by(EvalResult.created_at).limit(limit).offset(offset)

        results = await self.session.execute(query)
        total = await self.session.execute(count_query)

        return results.scalars().all(), total.scalar_one()

    async def get_completed_prompt_model_pairs(
        self, run_id: uuid.UUID
    ) -> set[tuple[str, str]]:
        """Get all (prompt_id, model_name) pairs that have been scored — for resume support."""
        result = await self.session.execute(
            select(EvalResult.prompt_id, EvalResult.model_name)
            .where(EvalResult.run_id == run_id)
            .where(EvalResult.overall_pass.is_not(None))  # has been judged
        )
        return {(row.prompt_id, row.model_name) for row in result.all()}

    # === Judge Scores ===

    async def save_scores(
        self,
        result_id: uuid.UUID,
        scores: dict[str, float],
        reasoning: dict[str, str],
        judge_model: str,
    ) -> list[JudgeScore]:
        """Save judge scores for all dimensions of a result."""
        score_objects = []
        for dimension, score_value in scores.items():
            score_obj = JudgeScore(
                result_id=result_id,
                dimension=dimension,
                score=score_value,
                reasoning=reasoning.get(dimension, ""),
                judge_model=judge_model,
            )
            self.session.add(score_obj)
            score_objects.append(score_obj)
        await self.session.flush()
        return score_objects

    # === Report Aggregation ===

    async def get_run_report(self, run_id: uuid.UUID) -> dict:
        """Generate aggregated report for an evaluation run."""
        run = await self.get_run(run_id)
        if not run:
            return {}

        # Get all results
        results_query = await self.session.execute(
            select(EvalResult).where(EvalResult.run_id == run_id)
        )
        results = results_query.scalars().all()

        if not results:
            return {
                "run_id": str(run_id),
                "run_name": run.name,
                "status": run.status,
                "total_prompts": 0,
                "total_evaluations": 0,
                "pass_rate": 0.0,
                "model_scores": {},
                "category_pass_rates": {},
                "worst_prompts": [],
            }

        total = len(results)
        passed = sum(1 for r in results if r.overall_pass is True)
        pass_rate = passed / total if total > 0 else 0.0

        # Aggregate scores per model per dimension
        model_scores: dict[str, dict[str, list[float]]] = {}
        category_results: dict[str, list[bool]] = {}
        prompt_scores: list[dict] = []

        for result in results:
            # Model dimension scores
            if result.model_name not in model_scores:
                model_scores[result.model_name] = {}
            for score in result.scores:
                if score.dimension not in model_scores[result.model_name]:
                    model_scores[result.model_name][score.dimension] = []
                model_scores[result.model_name][score.dimension].append(score.score)

            # Category pass rates
            if result.category not in category_results:
                category_results[result.category] = []
            if result.overall_pass is not None:
                category_results[result.category].append(result.overall_pass)

            # Track worst prompts (failed ones)
            if result.overall_pass is False:
                avg_score = (
                    sum(s.score for s in result.scores) / len(result.scores)
                    if result.scores
                    else 0.0
                )
                prompt_scores.append(
                    {
                        "prompt_id": result.prompt_id,
                        "model": result.model_name,
                        "category": result.category,
                        "avg_score": round(avg_score, 2),
                        "prompt_text": result.prompt_text[:100] + "..."
                        if len(result.prompt_text) > 100
                        else result.prompt_text,
                    }
                )

        # Average the model scores
        model_avgs: dict[str, dict[str, float]] = {}
        for model, dimensions in model_scores.items():
            model_avgs[model] = {
                dim: round(sum(vals) / len(vals), 2) for dim, vals in dimensions.items()
            }

        # Category pass rates
        cat_pass_rates: dict[str, float] = {}
        for cat, passes in category_results.items():
            cat_pass_rates[cat] = round(sum(passes) / len(passes), 2) if passes else 0.0

        # Sort worst prompts by avg score ascending
        prompt_scores.sort(key=lambda x: x["avg_score"])

        return {
            "run_id": str(run_id),
            "run_name": run.name,
            "status": run.status,
            "total_prompts": run.prompt_count,
            "total_evaluations": total,
            "pass_rate": round(pass_rate, 3),
            "model_scores": model_avgs,
            "category_pass_rates": cat_pass_rates,
            "worst_prompts": prompt_scores[:10],  # top 10 worst
        }

    async def calculate_and_update_pass_rate(self, run_id: uuid.UUID) -> float:
        """Calculate pass rate for a run and update the run record."""
        result = await self.session.execute(
            select(
                func.count().label("total"),
                func.count().filter(EvalResult.overall_pass.is_(True)).label("passed"),
            )
            .select_from(EvalResult)
            .where(EvalResult.run_id == run_id)
            .where(EvalResult.overall_pass.is_not(None))
        )
        row = result.one()
        total = row.total
        passed = row.passed
        pass_rate = passed / total if total > 0 else 0.0

        await self.update_run_status(run_id, "completed", pass_rate=pass_rate)
        return pass_rate

    # === Dead Letter Queue ===

    async def add_to_dlq(
        self,
        prompt_text: str,
        model_name: str,
        error_type: str,
        error_msg: str,
        run_id: uuid.UUID | None = None,
        payload: dict | None = None,
        max_retries: int = 3,
    ) -> DeadLetterQueue:
        """Add a failed evaluation to the dead letter queue."""
        # Exponential backoff: 1min for first retry
        next_retry = datetime.now(timezone.utc) + timedelta(minutes=1)

        dlq_item = DeadLetterQueue(
            run_id=run_id,
            prompt_text=prompt_text,
            model_name=model_name,
            error_type=error_type,
            error_msg=error_msg,
            payload=payload,
            max_retries=max_retries,
            next_retry=next_retry,
        )
        self.session.add(dlq_item)
        await self.session.flush()

        # Metrics
        from app.metrics import dlq_added_total, dlq_pending_total
        dlq_added_total.labels(error_type=error_type, provider=model_name).inc()
        dlq_pending_total.inc()

        logger.warning(
            "Added to DLQ",
            dlq_id=str(dlq_item.id),
            model=model_name,
            error_type=error_type,
        )
        return dlq_item

    async def get_retryable_dlq(self) -> Sequence[DeadLetterQueue]:
        """Get DLQ items ready for retry (next_retry < now and not exhausted)."""
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(DeadLetterQueue)
            .where(DeadLetterQueue.status == "pending")
            .where(DeadLetterQueue.next_retry <= now)
            .where(DeadLetterQueue.retry_count < DeadLetterQueue.max_retries)
            .order_by(DeadLetterQueue.next_retry)
            .limit(50)
        )
        return result.scalars().all()

    async def increment_dlq_retry(self, dlq_id: uuid.UUID) -> None:
        """Increment retry count and set next retry time with exponential backoff."""
        item = await self.session.get(DeadLetterQueue, dlq_id)
        if not item:
            return

        item.retry_count += 1

        if item.retry_count >= item.max_retries:
            item.status = "exhausted"
            from app.metrics import dlq_exhausted_total, dlq_pending_total
            dlq_exhausted_total.inc()
            dlq_pending_total.dec()
            logger.error(
                "DLQ item exhausted",
                dlq_id=str(dlq_id),
                model=item.model_name,
                retries=item.retry_count,
            )
        else:
            # Exponential backoff: 1min, 5min, 30min
            backoff_minutes = [1, 5, 30]
            delay = backoff_minutes[min(item.retry_count, len(backoff_minutes) - 1)]
            item.next_retry = datetime.now(timezone.utc) + timedelta(minutes=delay)

    async def mark_dlq_retried(self, dlq_id: uuid.UUID) -> None:
        """Mark a DLQ item as successfully retried."""
        from app.metrics import dlq_pending_total, dlq_retried_total
        dlq_retried_total.inc()
        dlq_pending_total.dec()
        await self.session.execute(
            update(DeadLetterQueue)
            .where(DeadLetterQueue.id == dlq_id)
            .values(status="retried")
        )

    async def get_dlq_stats(self) -> dict:
        """Get DLQ statistics for monitoring."""
        result = await self.session.execute(
            select(
                DeadLetterQueue.status,
                func.count().label("count"),
            )
            .group_by(DeadLetterQueue.status)
        )
        stats = {row.status: row.count for row in result.all()}
        return {
            "pending": stats.get("pending", 0),
            "retried": stats.get("retried", 0),
            "exhausted": stats.get("exhausted", 0),
            "total": sum(stats.values()),
        }
