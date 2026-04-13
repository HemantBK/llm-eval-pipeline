"""Initial schema — eval_runs, eval_results, judge_scores, dead_letter_queue.

Revision ID: 001
Revises: None
Create Date: 2026-04-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === eval_runs ===
    op.create_table(
        "eval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("config", postgresql.JSONB, nullable=True),
        sa.Column("prompt_count", sa.Integer, server_default="0"),
        sa.Column("pass_rate", sa.Float, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_eval_runs_status", "eval_runs", ["status"])
    op.create_index("idx_eval_runs_created", "eval_runs", ["created_at"])

    # === eval_results ===
    op.create_table(
        "eval_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("eval_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("prompt_id", sa.String(50), server_default=""),
        sa.Column("prompt_text", sa.Text, nullable=False),
        sa.Column("category", sa.String(50), server_default="general"),
        sa.Column("expected_behavior", sa.Text, server_default=""),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("raw_response", sa.Text, nullable=True),
        sa.Column("latency_ms", sa.Integer, server_default="0"),
        sa.Column("token_count", sa.Integer, server_default="0"),
        sa.Column("cached", sa.Boolean, server_default="false"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("overall_pass", sa.Boolean, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_results_run_id", "eval_results", ["run_id"])
    op.create_index("idx_results_model", "eval_results", ["model_name"])
    op.create_index("idx_results_category", "eval_results", ["category"])
    op.create_index("idx_results_prompt_id", "eval_results", ["prompt_id"])

    # === judge_scores ===
    op.create_table(
        "judge_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("eval_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dimension", sa.String(50), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("reasoning", sa.Text, server_default=""),
        sa.Column("judge_model", sa.String(100), server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_scores_result_id", "judge_scores", ["result_id"])
    op.create_index("idx_scores_dimension", "judge_scores", ["dimension"])

    # === dead_letter_queue ===
    op.create_table(
        "dead_letter_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("prompt_text", sa.Text, nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("error_type", sa.String(50), nullable=False),
        sa.Column("error_msg", sa.Text, server_default=""),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.Column("retry_count", sa.Integer, server_default="0"),
        sa.Column("max_retries", sa.Integer, server_default="3"),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("next_retry", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_dlq_status", "dead_letter_queue", ["status"])
    op.create_index("idx_dlq_next_retry", "dead_letter_queue", ["next_retry"])


def downgrade() -> None:
    op.drop_table("dead_letter_queue")
    op.drop_table("judge_scores")
    op.drop_table("eval_results")
    op.drop_table("eval_runs")
