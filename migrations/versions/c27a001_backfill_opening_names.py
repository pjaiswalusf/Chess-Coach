"""Fill missing display names from saved Chess.com opening URLs."""

import sqlalchemy as sa
from alembic import op

from chess_coach.infrastructure.chesscom.opening_names import opening_name_from_url

revision = "c27a001"
down_revision = "c26a001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    games = sa.table(
        "games",
        sa.column("id", sa.Integer),
        sa.column("opening_name", sa.Text),
        sa.column("eco_url", sa.Text),
    )
    candidates = connection.execute(
        sa.select(games.c.id, games.c.eco_url).where(
            sa.func.coalesce(sa.func.trim(games.c.opening_name), "") == "",
            games.c.eco_url.is_not(None),
        )
    ).all()
    values = [
        {"game_id": game_id, "name": name}
        for game_id, url in candidates
        if (name := opening_name_from_url(url))
    ]
    if values:
        connection.execute(
            games.update()
            .where(games.c.id == sa.bindparam("game_id"))
            .values(opening_name=sa.bindparam("name")),
            values,
        )


def downgrade() -> None:
    # Display metadata is compatible with the previous schema.
    pass
