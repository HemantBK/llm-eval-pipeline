"""SQLAlchemy async ORM models for the evaluation pipeline."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class EvalRun(Base):
    """Top-level evaluation session — groups multiple prompt evaluations together."""

    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )  # pending, running, completed, failed, timed_out
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # models, rubric, params
    prompt_count: Mapped[int] = mapped_column(Integer, default=0)
    pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    results: Mapped[list["EvalResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("idx_eval_runs_status", "status"),
        Index("idx_eval_runs_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<EvalRun {self.id} name={self.name!r} status={self.status}>"


class EvalResult(Base):
    """A single LLM response to a prompt — stores raw response + metadata."""

    __tablename__ = "eval_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )

    # Prompt info
    prompt_id: Mapped[str] = mapped_column(String(50), default="")  # human ID: "CS-001"
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="general")
    expected_behavior: Mapped[str] = mapped_column(Text, default="")

    # Model info
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)  # "gemini-2.0-flash"
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # "gemini", "openai", "vllm"

    # Response
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Overall pass/fail
    overall_pass: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    run: Mapped["EvalRun"] = relationship(back_populates="results")
    scores: Mapped[list["JudgeScore"]] = relationship(
        back_populates="result", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("idx_results_run_id", "run_id"),
        Index("idx_results_model", "model_name"),
        Index("idx_results_category", "category"),
        Index("idx_results_prompt_id", "prompt_id"),
    )

    def __repr__(self) -> str:
        return f"<EvalResult {self.id} model={self.model_name} pass={self.overall_pass}>"


class JudgeScore(Base):
    """A single dimension score from the judge LLM."""

    __tablename__ = "judge_scores"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_results.id", ondelete="CASCADE"), nullable=False
    )

    dimension: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # accuracy, safety, hallucination, reasoning, code_quality, completeness
    score: Mapped[float] = mapped_column(Float, nullable=False)  # 1.0 - 5.0
    reasoning: Mapped[str] = mapped_column(Text, default="")
    judge_model: Mapped[str] = mapped_column(String(100), default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    result: Mapped["EvalResult"] = relationship(back_populates="scores")

    __table_args__ = (
        Index("idx_scores_result_id", "result_id"),
        Index("idx_scores_dimension", "dimension"),
    )

    def __repr__(self) -> str:
        return f"<JudgeScore {self.dimension}={self.score}>"


class DeadLetterQueue(Base):
    """Failed evaluations stored for retry. Nothing is silently lost."""

    __tablename__ = "dead_letter_queue"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # What failed
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Error details
    error_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # timeout, rate_limit, parse_error, provider_down, circuit_open
    error_msg: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # full request for replay

    # Retry tracking
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, retried, exhausted
    next_retry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_dlq_status", "status"),
        Index("idx_dlq_next_retry", "next_retry"),
    )

    def __repr__(self) -> str:
        return f"<DLQ {self.id} model={self.model_name} status={self.status} retries={self.retry_count}/{self.max_retries}>"
