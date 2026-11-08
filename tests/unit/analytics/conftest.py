from datetime import UTC, datetime, timedelta

import pytest

from chess_coach.analytics.contracts import AnalysisStatus, GameEvidence, MoveEvidence
from chess_coach.analytics.sample_policy import severity
from chess_coach.domain.feature_models import GamePhase
from chess_coach.domain.game_records import GameResult, PlayerColor


@pytest.fixture
def factory():
    def create(
        game_id=1,
        losses=(0, 20, 95, 180, None),
        phases=None,
        color=PlayerColor.WHITE,
        result=GameResult.WIN,
        status=AnalysisStatus.DONE,
        **overrides,
    ):
        phases = phases or [
            GamePhase.OPENING,
            GamePhase.OPENING,
            GamePhase.MIDDLEGAME,
            GamePhase.MIDDLEGAME,
            GamePhase.ENDGAME,
        ]
        moves = (
            tuple(
                MoveEvidence(
                    game_id=game_id,
                    ply=2 * i + (1 if color == PlayerColor.WHITE else 2),
                    move_number=i + 1,
                    mover=color,
                    phase=phases[i % len(phases)],
                    loss_cp=loss,
                    severity=severity(loss),
                    before_cp=0 if loss is not None else None,
                    after_cp=-int(loss) if loss is not None else None,
                    mate_before=None if loss is not None else 3,
                    in_check=False,
                    after_capture=False,
                    castled=False,
                )
                for i, loss in enumerate(losses)
            )
            if status == AnalysisStatus.DONE
            else ()
        )
        return GameEvidence(
            game_id=game_id,
            played_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=game_id),
            color=color,
            result=result,
            time_class="blitz",
            time_control="180",
            eco="B12",
            provenance="pgn_declaration",
            analysis_status=status,
            expected_player_moves=len(losses),
            moves=moves,
            features_available=True,
            **overrides,
        )

    return create
