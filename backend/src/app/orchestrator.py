"""Async orchestrator — the core engine that drives evaluation runs.

Fan-out: send each prompt to each model concurrently (with backpressure)
Fan-in: collect responses, send to judge, write scores to DB

This is the beating heart of the pipeline. Everything else exists to support it.
"""

import asyncio
import time as _time
import uuid

import structlog

from app.errors.exceptions import (
    CircuitOpenError,
    JudgeParseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.judge.engine import JudgeEngine
from app.judge.rubrics import auto_select_rubric, get_rubric
from app.providers.base import GenerateConfig
from app.providers.registry import ProviderRegistry
from app.repositories import EvalRepository

logger = structlog.get_logger()

# Per-provider concurrency limits (backpressure)
PROVIDER_CONCURRENCY = {
    "gemini": 3,  # 15 RPM → ~3 concurrent is safe
    "openai": 10,  # 60 RPM → ~10 concurrent
    "vllm": 50,  # local, go wild
    "ollama": 5,  # CPU-bound, don't overwhelm
}

# Overall run timeout
RUN_TIMEOUT_S = 1800  # 30 minutes hard cap


class EvalOrchestrator:
    """
    Drives evaluation runs end-to-end.

    Usage:
        orchestrator = EvalOrchestrator(registry, judge, repo)

        # Single prompt (what n8n calls):
        results = await orchestrator.evaluate_prompt(prompt, models, rubric)

        # Batch run (CLI/direct):
        await orchestrator.execute_run(run_id)
    """

    def __init__(
        self,
        registry: ProviderRegistry,
        judge: JudgeEngine,
        repo: EvalRepository,
    ) -> None:
        self._registry = registry
        self._judge = judge
        self._repo = repo

        # Per-provider semaphores for backpressure
        self._semaphores: dict[str, asyncio.Semaphore] = {
            name: asyncio.Semaphore(PROVIDER_CONCURRENCY.get(name, 5))
            for name in registry.available_providers
        }

    # =========================================================================
    # Single Prompt Evaluation (what n8n calls via POST /eval/prompt)
    # =========================================================================

    async def evaluate_prompt(
        self,
        prompt_text: str,
        prompt_id: str,
        category: str,
        expected_behavior: str,
        models: list[str],
        rubric_name: str = "auto",
        run_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """
        Evaluate a single prompt against multiple models.

        Returns a list of scored results, one per model.
        This is the PRIMARY method that n8n calls.
        """
        # Auto-select rubric if not specified
        rubric = auto_select_rubric(category) if rubric_name == "auto" else get_rubric(rubric_name)

        # If no run_id, create a one-off run
        if run_id is None:
            run = await self._repo.create_run(
                name=f"single-{prompt_id or 'prompt'}",
                config={"models": models, "rubric": rubric.name},
                prompt_count=1,
            )
            run_id = run.id
            await self._repo.update_run_status(run_id, "running")

        # Fan-out to all models concurrently
        tasks = []
        for model_name in models:
            tasks.append(
                self._evaluate_single(
                    run_id=run_id,
                    prompt_text=prompt_text,
                    prompt_id=prompt_id,
                    category=category,
                    expected_behavior=expected_behavior,
                    model_name=model_name,
                    rubric=rubric,
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results — separate successes from failures
        scored_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                model = models[i]
                logger.error(
                    "Prompt evaluation failed",
                    model=model,
                    prompt_id=prompt_id,
                    error=str(result),
                )
                # Add to DLQ
                await self._repo.add_to_dlq(
                    prompt_text=prompt_text,
                    model_name=model,
                    error_type=type(result).__name__,
                    error_msg=str(result),
                    run_id=run_id,
                    payload={
                        "prompt_id": prompt_id,
                        "category": category,
                        "expected_behavior": expected_behavior,
                        "rubric": rubric.name,
                    },
                )
                # Return error result so n8n knows what failed
                scored_results.append(
                    {
                        "model": model,
                        "provider": model,
                        "response": "",
                        "latency_ms": 0,
                        "cached": False,
                        "scores": {},
                        "reasoning": {},
                        "overall_pass": False,
                        "error": str(result),
                    }
                )
            else:
                scored_results.append(result)

        # Update run pass rate
        await self._repo.calculate_and_update_pass_rate(run_id)

        return scored_results

    # =========================================================================
    # Batch Run (CLI/direct via POST /eval/batch)
    # =========================================================================

    async def execute_run(
        self,
        run_id: uuid.UUID,
        prompts: list[dict],
        models: list[str],
        rubric_name: str = "auto",
        resume: bool = False,
    ) -> None:
        """
        Execute a full batch evaluation run.

        Fan-out all prompts × models concurrently with backpressure.
        Supports resume from checkpoint (skip already-scored pairs).
        """
        from app.metrics import (
            eval_run_duration_seconds,
            eval_runs_active,
            eval_runs_total,
        )

        await self._repo.update_run_status(run_id, "running")
        eval_runs_active.inc()
        run_start = _time.perf_counter()

        # Resume support: skip already-completed pairs
        completed_pairs: set[tuple[str, str]] = set()
        if resume:
            completed_pairs = await self._repo.get_completed_prompt_model_pairs(run_id)
            logger.info(
                "Resuming run",
                run_id=str(run_id),
                already_completed=len(completed_pairs),
            )

        try:
            async with asyncio.timeout(RUN_TIMEOUT_S):
                async with asyncio.TaskGroup() as tg:
                    for prompt_data in prompts:
                        prompt_id = prompt_data.get("prompt_id", "")
                        category = prompt_data.get("category", "general")

                        # Auto-select rubric per prompt category
                        rubric = (
                            auto_select_rubric(category)
                            if rubric_name == "auto"
                            else get_rubric(rubric_name)
                        )

                        for model_name in models:
                            # Skip if already completed (resume)
                            if (prompt_id, model_name) in completed_pairs:
                                logger.debug(
                                    "Skipping completed",
                                    prompt_id=prompt_id,
                                    model=model_name,
                                )
                                continue

                            tg.create_task(
                                self._evaluate_single_safe(
                                    run_id=run_id,
                                    prompt_text=prompt_data["prompt"],
                                    prompt_id=prompt_id,
                                    category=category,
                                    expected_behavior=prompt_data.get("expected_behavior", ""),
                                    model_name=model_name,
                                    rubric=rubric,
                                )
                            )

        except TimeoutError:
            logger.error("Run timed out", run_id=str(run_id), timeout_s=RUN_TIMEOUT_S)
            await self._repo.update_run_status(run_id, "timed_out")
            return
        except ExceptionGroup as eg:
            logger.error(
                "Run had failures",
                run_id=str(run_id),
                error_count=len(eg.exceptions),
            )

        # Calculate final pass rate + metrics
        eval_runs_active.dec()
        eval_run_duration_seconds.observe(_time.perf_counter() - run_start)

        pass_rate = await self._repo.calculate_and_update_pass_rate(run_id)
        eval_runs_total.labels(status="completed").inc()
        logger.info(
            "Run completed",
            run_id=str(run_id),
            pass_rate=round(pass_rate, 3),
        )

    # =========================================================================
    # Internal: single prompt × model evaluation
    # =========================================================================

    async def _evaluate_single(
        self,
        run_id: uuid.UUID,
        prompt_text: str,
        prompt_id: str,
        category: str,
        expected_behavior: str,
        model_name: str,
        rubric,
    ) -> dict:
        """
        Evaluate a single prompt with a single model.

        Flow: semaphore acquire → LLM call → judge → save to DB → return result
        """
        provider_name = self._resolve_provider(model_name)
        sem = self._semaphores.get(provider_name, asyncio.Semaphore(5))

        async with sem:
            # 1. Call LLM provider (cache + rate limit + retry handled by registry)
            llm_response = await self._registry.generate(
                provider_name=provider_name,
                prompt=prompt_text,
                config=GenerateConfig(temperature=0.7, max_tokens=2048, timeout_s=30.0),
            )

            # 2. Save raw response to DB
            result = await self._repo.save_result(
                run_id=run_id,
                prompt_id=prompt_id,
                prompt_text=prompt_text,
                category=category,
                expected_behavior=expected_behavior,
                model_name=llm_response.model_name,
                provider=llm_response.provider,
                raw_response=llm_response.text,
                latency_ms=llm_response.latency_ms,
                token_count=llm_response.token_count,
                cached=llm_response.cached,
            )

            # 3. Judge the response
            verdict = await self._judge.evaluate(
                prompt_text=prompt_text,
                category=category,
                expected_behavior=expected_behavior,
                model_response=llm_response.text,
                model_name=llm_response.model_name,
                rubric_name=rubric.name,
            )

            # 4. Save scores to DB
            await self._repo.save_scores(
                result_id=result.id,
                scores=verdict.scores,
                reasoning=verdict.reasoning,
                judge_model=verdict.judge_model,
            )

            # 5. Update overall_pass on the result
            from sqlalchemy import update as sa_update

            from app.models import EvalResult

            await self._repo.session.execute(
                sa_update(EvalResult)
                .where(EvalResult.id == result.id)
                .values(overall_pass=verdict.overall_pass)
            )

            # 6. Record evaluation metrics
            from app.metrics import eval_completed_total, eval_failed_total, eval_passed_total
            from app.metrics import judge_score as judge_score_metric

            eval_completed_total.labels(provider=provider_name, category=category).inc()
            if verdict.overall_pass:
                eval_passed_total.labels(provider=provider_name, category=category).inc()
            else:
                eval_failed_total.labels(provider=provider_name, category=category).inc()

            for dim_name, dim_score in verdict.scores.items():
                judge_score_metric.labels(dimension=dim_name, category=category).observe(dim_score)

            logger.info(
                "Evaluation complete",
                prompt_id=prompt_id,
                model=llm_response.model_name,
                overall_pass=verdict.overall_pass,
                latency_ms=llm_response.latency_ms,
                cached=llm_response.cached,
            )

            return {
                "model": llm_response.model_name,
                "provider": llm_response.provider,
                "response": llm_response.text,
                "latency_ms": llm_response.latency_ms,
                "cached": llm_response.cached,
                "scores": verdict.scores,
                "reasoning": verdict.reasoning,
                "overall_pass": verdict.overall_pass,
            }

    async def _evaluate_single_safe(self, **kwargs) -> dict | None:
        """
        Wrapper for batch runs — catches errors and sends to DLQ instead of crashing the TaskGroup.
        """
        try:
            return await self._evaluate_single(**kwargs)
        except (
            LLMProviderError,
            LLMTimeoutError,
            LLMRateLimitError,
            CircuitOpenError,
            JudgeParseError,
        ) as e:
            logger.error(
                "Evaluation failed, sending to DLQ",
                prompt_id=kwargs.get("prompt_id"),
                model=kwargs.get("model_name"),
                error=str(e),
            )
            await self._repo.add_to_dlq(
                prompt_text=kwargs["prompt_text"],
                model_name=kwargs["model_name"],
                error_type=type(e).__name__,
                error_msg=str(e),
                run_id=kwargs["run_id"],
                payload={
                    "prompt_id": kwargs.get("prompt_id", ""),
                    "category": kwargs.get("category", ""),
                    "expected_behavior": kwargs.get("expected_behavior", ""),
                },
            )
            return None
        except Exception:
            logger.exception(
                "Unexpected evaluation error",
                prompt_id=kwargs.get("prompt_id"),
                model=kwargs.get("model_name"),
            )
            return None

    def _resolve_provider(self, model_name: str) -> str:
        """
        Resolve a model name to its provider.

        If the model_name IS a provider name (gemini, openai, vllm, ollama), return it.
        Otherwise, try to infer the provider from the model name.
        """
        if model_name in self._registry.available_providers:
            return model_name

        # Infer from model name patterns
        model_lower = model_name.lower()
        if "gemini" in model_lower:
            return "gemini"
        elif "gpt" in model_lower:
            return "openai"
        elif "llama" in model_lower or "mistral" in model_lower:
            # Could be vllm or ollama — prefer vllm if available
            if "vllm" in self._registry.available_providers:
                return "vllm"
            return "ollama"

        # Default to the model_name itself and let the registry handle the error
        return model_name
