"""Independent coaching jobs, metadata and validated result cache."""

import sqlalchemy as sa
from alembic import op

revision = "c14a001"
down_revision = "f11a001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coaching_outputs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("output_type", sa.String(16), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("model_digest", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("generation_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(64)),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("cache_key"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'insufficient_evidence', 'failed')",
            name="coaching_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="coaching_attempts"),
    )


def downgrade() -> None:
    op.drop_table("coaching_outputs")
