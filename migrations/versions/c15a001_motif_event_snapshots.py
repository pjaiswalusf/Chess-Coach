"""Persist versioned verified motif events independently of model suggestions."""

import sqlalchemy as sa
from alembic import op

revision = "c15a001"
down_revision = "c14a001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "motif_event_snapshots",
        sa.Column("evidence_hash", sa.String(64), primary_key=True),
        sa.Column(
            "game_id",
            sa.Integer(),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ply", sa.Integer(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    # The older worker does not recognize motif jobs in the shared queue.
    op.execute(sa.text("DELETE FROM coaching_outputs WHERE output_type = 'motif'"))
    op.drop_table("motif_event_snapshots")
