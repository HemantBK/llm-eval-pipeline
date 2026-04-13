"""Evaluation endpoints — the core API that n8n calls."""

from uuid import UUID

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.deps import DB, Auth, Redis
from app.judge.engine import JudgeEngine
from app.judge.rubrics import list_rubrics
from app.orchestrator import EvalOrchestrator
from app.providers.registry import create_registry
from app.repositories import EvalRepository

router = APIRouter()
logger = structlog.get_logger()


# --- Request/Response Models ---


class EvalPromptRequest(BaseModel):
    """Request body for single prompt evaluation (what n8n sends)."""

    prompt: str = Field(..., min_length=1, description="The prompt text to evaluate")
    prompt_id: str = Field(default="", description="Human-readable prompt ID, e.g. CS-001")
    category: str = Field(
        default="general",
        description="Category: coding, safety, reasoning, etc.",
    )
    expected_behavior: str = Field(default="", description="What the model should do")
    models: list[str] = Field(
        default=["gemini"],
        description="Which models to evaluate: gemini, openai, vllm, ollama",
    )
    rubric: str = Field(
        default="auto",
        description="Rubric: auto, default, safety, coding, hallucination",
    )


class ScoreResult(BaseModel):
    """Scores for a single model's response."""

    model: str
    provider: str
    response: str
    latency_ms: int
    cached: bool
    scores: dict[str, float]
    reasoning: dict[str, str]
    overall_pass: bool
    error: str | None = None


class EvalPromptResponse(BaseModel):
    """Response from /eval/prompt."""

    prompt_id: str
    results: list[ScoreResult]


class EvalBatchRequest(BaseModel):
    """Request body for batch evaluation (CLI/direct use)."""

    run_name: str = Field(..., min_length=1)
    prompts: list[EvalPromptRequest]
    models: list[str] = Field(default=["gemini"])
    rubric: str = Field(default="auto")


class EvalBatchResponse(BaseModel):
    """Response from /eval/batch — returns run_id for async tracking."""

    run_id: UUID
    status: str = "accepted"
    prompt_count: int
    models: list[str]


class EvalReportResponse(BaseModel):
    """Aggregated evaluation report."""

    run_id: UUID
    run_name: str
    status: str
    total_prompts: int
    total_evaluations: int
    pass_rate: float
    model_scores: dict[str, dict[str, float]]
    category_pass_rates: dict[str, float]
    worst_prompts: list[dict]


# --- Helper: Build orchestrator from dependencies ---


def _build_orchestrator(db, redis) -> EvalOrchestrator:
    """Build an orchestrator with all dependencies wired together."""
    registry = create_registry(redis)
    judge = JudgeEngine(registry)
    repo = EvalRepository(db)
    return EvalOrchestrator(registry, judge, repo)


# --- Endpoints ---


@router.post("/prompt", response_model=EvalPromptResponse)
async def evaluate_prompt(
    request: EvalPromptRequest,
    db: DB,
    redis: Redis,
    _auth: Auth,
) -> EvalPromptResponse:
    """
    Evaluate a single prompt against specified models.

    This is the PRIMARY endpoint that n8n calls.
    Full pipeline per call: cache → rate limit → LLM → judge → score → DB → return.
    """
    logger.info(
        "Evaluating prompt",
        prompt_id=request.prompt_id,
        category=request.category,
        models=request.models,
    )

    orchestrator = _build_orchestrator(db, redis)

    results = await orchestrator.evaluate_prompt(
        prompt_text=request.prompt,
        prompt_id=request.prompt_id,
        category=request.category,
        expected_behavior=request.expected_behavior,
        models=request.models,
        rubric_name=request.rubric,
    )

    return EvalPromptResponse(
        prompt_id=request.prompt_id,
        results=[ScoreResult(**r) for r in results],
    )


@router.post("/batch", response_model=EvalBatchResponse, status_code=202)
async def evaluate_batch(
    request: EvalBatchRequest,
    db: DB,
    redis: Redis,
    _auth: Auth,
    background_tasks: BackgroundTasks,
) -> EvalBatchResponse:
    """
    Submit a batch of prompts for evaluation (async).

    Returns immediately with a run_id (202 Accepted).
    Use GET /eval/results/{run_id} to check progress.
    Use GET /eval/report/{run_id} for aggregated report.
    """
    logger.info(
        "Batch eval submitted",
        run_name=request.run_name,
        prompt_count=len(request.prompts),
        models=request.models,
    )

    repo = EvalRepository(db)

    # Create the run in DB
    run = await repo.create_run(
        name=request.run_name,
        config={"models": request.models, "rubric": request.rubric},
        prompt_count=len(request.prompts),
    )

    # Convert prompts to dict format for orchestrator
    prompt_dicts = [
        {
            "prompt": p.prompt,
            "prompt_id": p.prompt_id,
            "category": p.category,
            "expected_behavior": p.expected_behavior,
        }
        for p in request.prompts
    ]

    # Dispatch to background — returns immediately
    background_tasks.add_task(
        _run_batch_in_background,
        run_id=run.id,
        prompts=prompt_dicts,
        models=request.models,
        rubric_name=request.rubric,
        db_url=str(db.get_bind().url) if hasattr(db, "get_bind") else None,
        redis=redis,
    )

    return EvalBatchResponse(
        run_id=run.id,
        status="accepted",
        prompt_count=len(request.prompts),
        models=request.models,
    )


async def _run_batch_in_background(
    run_id: UUID,
    prompts: list[dict],
    models: list[str],
    rubric_name: str,
    db_url: str | None,
    redis,
) -> None:
    """Background task for batch evaluation. Gets its own DB session."""
    from app.deps import _session_factory

    async with _session_factory() as session:
        try:
            repo = EvalRepository(session)
            registry = create_registry(redis)
            judge = JudgeEngine(registry)
            orchestrator = EvalOrchestrator(registry, judge, repo)

            await orchestrator.execute_run(
                run_id=run_id,
                prompts=prompts,
                models=models,
                rubric_name=rubric_name,
            )
            await session.commit()
        except Exception:
            logger.exception("Background batch failed", run_id=str(run_id))
            await session.rollback()
            try:
                repo2 = EvalRepository(session)
                await repo2.update_run_status(run_id, "failed")
                await session.commit()
            except Exception:
                pass


@router.post("/run/{run_id}/resume", response_model=EvalBatchResponse)
async def resume_run(
    run_id: UUID,
    db: DB,
    redis: Redis,
    _auth: Auth,
    background_tasks: BackgroundTasks,
) -> EvalBatchResponse:
    """
    Resume a failed or partial evaluation run.

    Skips already-scored prompt+model pairs and retries only what's missing.
    """
    repo = EvalRepository(db)
    run = await repo.get_run(run_id)

    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if run.status == "completed":
        raise HTTPException(status_code=400, detail="Run already completed")

    config = run.config or {}
    models = config.get("models", ["gemini"])
    rubric_name = config.get("rubric", "auto")

    # Reconstruct prompts from existing results
    results, _ = await repo.get_results_for_run(run_id, limit=10000)
    seen_prompts: dict[str, dict] = {}
    for result in results:
        if result.prompt_id not in seen_prompts:
            seen_prompts[result.prompt_id] = {
                "prompt": result.prompt_text,
                "prompt_id": result.prompt_id,
                "category": result.category,
                "expected_behavior": result.expected_behavior,
            }

    prompt_dicts = list(seen_prompts.values())

    logger.info(
        "Resuming run",
        run_id=str(run_id),
        prompts=len(prompt_dicts),
        models=models,
    )

    background_tasks.add_task(
        _run_resume_in_background,
        run_id=run_id,
        prompts=prompt_dicts,
        models=models,
        rubric_name=rubric_name,
        redis=redis,
    )

    return EvalBatchResponse(
        run_id=run_id,
        status="resuming",
        prompt_count=len(prompt_dicts),
        models=models,
    )


async def _run_resume_in_background(
    run_id: UUID,
    prompts: list[dict],
    models: list[str],
    rubric_name: str,
    redis,
) -> None:
    """Background task for resuming a run."""
    from app.deps import _session_factory

    async with _session_factory() as session:
        try:
            repo = EvalRepository(session)
            registry = create_registry(redis)
            judge = JudgeEngine(registry)
            orchestrator = EvalOrchestrator(registry, judge, repo)

            await orchestrator.execute_run(
                run_id=run_id,
                prompts=prompts,
                models=models,
                rubric_name=rubric_name,
                resume=True,  # skip already-scored pairs
            )
            await session.commit()
        except Exception:
            logger.exception("Resume failed", run_id=str(run_id))
            await session.rollback()


@router.get("/results/{run_id}")
async def get_results(
    run_id: UUID,
    db: DB,
    _auth: Auth,
    model: str | None = None,
    category: str | None = None,
    page: int = 1,
    limit: int = 50,
) -> dict:
    """Get paginated results for an evaluation run."""
    repo = EvalRepository(db)
    run = await repo.get_run(run_id)

    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    offset = (page - 1) * limit
    results, total = await repo.get_results_for_run(
        run_id, model=model, category=category, limit=limit, offset=offset
    )

    return {
        "run_id": str(run_id),
        "run_name": run.name,
        "status": run.status,
        "page": page,
        "limit": limit,
        "total": total,
        "results": [
            {
                "id": str(r.id),
                "prompt_id": r.prompt_id,
                "category": r.category,
                "model_name": r.model_name,
                "provider": r.provider,
                "response": r.raw_response[:500] if r.raw_response else "",
                "latency_ms": r.latency_ms,
                "cached": r.cached,
                "overall_pass": r.overall_pass,
                "error": r.error,
                "scores": {s.dimension: s.score for s in r.scores},
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in results
        ],
    }


@router.get("/report/{run_id}")
async def get_report(
    run_id: UUID,
    db: DB,
    _auth: Auth,
) -> dict:
    """Get aggregated evaluation report for a run."""
    repo = EvalRepository(db)
    report = await repo.get_run_report(run_id)

    if not report:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return report


@router.get("/runs")
async def list_runs(
    db: DB,
    _auth: Auth,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List all evaluation runs."""
    repo = EvalRepository(db)
    runs = await repo.list_runs(limit=limit, offset=offset)

    return {
        "runs": [
            {
                "id": str(r.id),
                "name": r.name,
                "status": r.status,
                "prompt_count": r.prompt_count,
                "pass_rate": r.pass_rate,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in runs
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/rubrics")
async def get_rubrics(_auth: Auth) -> dict:
    """List all available scoring rubrics."""
    return {"rubrics": list_rubrics()}


@router.get("/providers")
async def get_providers(redis: Redis, _auth: Auth) -> dict:
    """Get status of all LLM providers (circuit breaker state, rate limit usage)."""
    registry = create_registry(redis)
    return await registry.get_status()
