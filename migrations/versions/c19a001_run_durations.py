"""Persist monotonic import and analysis durations."""

import sqlalchemy as sa
from alembic import op

revision = "c19a001"
down_revision = "c18a001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("import_runs", sa.Column("duration_ms", sa.Integer(), nullable=True))
    op.add_column(
        "analysis_runs", sa.Column("active_duration_ms", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "active_duration_ms")
    op.drop_column("import_runs", "duration_ms")
