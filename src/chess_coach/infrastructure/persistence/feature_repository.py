"""Feature snapshots never modify stored game or engine evidence."""

from dataclasses import asdict, dataclass

import chess
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from chess_coach.analytics.feature_config import DEFAULT_CONFIG
from chess_coach.analytics.features import FeatureInputError
from chess_coach.application.parse_imported_games import ParseInput
from chess_coach.domain.analysis import fingerprint
from chess_coach.domain.feature_models import (
    FEATURE_EXTRACTOR_VERSION,
    PHASE_CLASSIFIER_VERSION,
    FeatureAnalysis,
    MoveFeatures,
)
from chess_coach.domain.game_records import PARSER_VERSION, ParseStatus
from chess_coach.infrastructure.persistence.analysis_repository import source_hash
from chess_coach.infrastructure.persistence.models import (
    Game,
    GameAnalysisState,
    MoveAnalysis,
    MoveFeature,
    TrackedPlayer,
)


@dataclass(frozen=True)
class FeatureSnapshot:
    source: ParseInput
    analyses: tuple[FeatureAnalysis, ...]
    profile_hash: str
    input_hash: str
    expected_plies: int


QUERY_FIELDS = (
    "phase",
    "played_is_capture",
    "played_gives_check",
    "played_is_castling",
    "material_balance_before",
    "material_balance_after",
    "engine_advantage_before",
    "advantage_lost",
    "time_used_seconds",
    "under_time_pressure",
)


class FeatureRepository:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    def candidates(self, username: str) -> list[int]:
        with self.sessions() as s:
            return list(
                s.scalars(
                    select(Game.id)
                    .join(TrackedPlayer)
                    .where(
                        TrackedPlayer.username == username.strip().casefold(),
                        Game.parse_status == ParseStatus.READY,
                    )
                    .order_by(Game.id)
                )
            )

    def _load(self, s: Session, game_id: int, profile_hash: str) -> FeatureSnapshot:
        game = s.get(Game, game_id)
        if (
            game is None
            or game.parse_status != ParseStatus.READY
            or game.parser_version != PARSER_VERSION
            or game.chess_library_version != chess.__version__
        ):
            raise FeatureInputError("GAME_REVALIDATION_REQUIRED")
        player = s.get(TrackedPlayer, game.tracked_player_id)
        assert player is not None
        source = ParseInput(
            game.id,
            game.raw_pgn,
            player.username,
            game.platform,
            game.white_username,
            game.black_username,
            game.source_evidence,
        )
        total = (game.parsed_metadata or {}).get("total_plies")
        if type(total) is not int or total < 0:
            raise FeatureInputError("GAME_REVALIDATION_REQUIRED")
        analyses = []
        if profile_hash != "board-only":
            states = list(
                s.scalars(
                    select(GameAnalysisState).where(
                        GameAnalysisState.game_id == game_id,
                        GameAnalysisState.profile_hash == profile_hash,
                    )
                )
            )
            if (
                len(states) != 1
                or states[0].status != "done"
                or states[0].source_hash != source_hash(game)
            ):
                raise FeatureInputError("ANALYSIS_NOT_READY")
            rows = list(
                s.scalars(
                    select(MoveAnalysis)
                    .where(
                        MoveAnalysis.game_id == game_id,
                        MoveAnalysis.profile_hash == profile_hash,
                        MoveAnalysis.analysis_version == states[0].analysis_version,
                    )
                    .order_by(MoveAnalysis.ply)
                )
            )
            for r in rows:
                analyses.append(
                    FeatureAnalysis(
                        ply=r.ply,
                        fen_before=r.fen_before,
                        played_move_uci=r.played_move_uci,
                        best_move_uci=r.best_move_uci,
                        eval_before_cp_white=r.eval_before_cp_white,
                        eval_after_cp_white=r.eval_after_cp_white,
                        mate_before_white=r.mate_before_white,
                        mate_after_white=r.mate_after_white,
                        mate_before_winner=r.mate_before_winner,
                        mate_after_winner=r.mate_after_winner,
                        is_critical_error=None
                        if r.severity is None
                        else r.severity == "critical",
                    )
                )
        identity = fingerprint(
            [
                asdict(source),
                source_hash(game),
                profile_hash,
                [a.model_dump(mode="json") for a in analyses],
                asdict(DEFAULT_CONFIG),
                FEATURE_EXTRACTOR_VERSION,
                PHASE_CLASSIFIER_VERSION,
                PARSER_VERSION,
                chess.__version__,
            ]
        )
        return FeatureSnapshot(source, tuple(analyses), profile_hash, identity, total)

    def load(self, game_id: int, profile_hash: str) -> FeatureSnapshot:
        with self.sessions() as s:
            return self._load(s, game_id, profile_hash)

    def _rows(self, s: Session, snapshot: FeatureSnapshot) -> list[MoveFeature]:
        return list(
            s.scalars(
                select(MoveFeature)
                .where(
                    MoveFeature.game_id == snapshot.source.game_id,
                    MoveFeature.feature_version == FEATURE_EXTRACTOR_VERSION,
                    MoveFeature.input_hash == snapshot.input_hash,
                )
                .order_by(MoveFeature.ply)
            )
        )

    def get(self, snapshot: FeatureSnapshot) -> list[MoveFeatures]:
        with self.sessions() as s:
            result = []
            for row in self._rows(s, snapshot):
                feature = MoveFeatures.model_validate(row.features_json)
                if (
                    row.content_hash != fingerprint(row.features_json)
                    or feature.game_id != row.game_id
                    or feature.ply != row.ply
                    or feature.feature_version != row.feature_version
                    or feature.phase_classifier_version != row.phase_classifier_version
                    or row.profile_hash != snapshot.profile_hash
                    or any(getattr(row, k) != getattr(feature, k) for k in QUERY_FIELDS)
                ):
                    raise FeatureInputError("FEATURE_CONTENT_INVALID", row.ply)
                result.append(feature)
            return result

    def complete(self, snapshot: FeatureSnapshot, plies: int) -> bool:
        try:
            rows = self.get(snapshot)
        except ValueError:
            return False
        return [r.ply for r in rows] == list(range(1, plies + 1))

    def save(self, snapshot: FeatureSnapshot, features: list[MoveFeatures]) -> None:
        # Revalidate even models constructed through Pydantic's unchecked copy API.
        features = [MoveFeatures.model_validate(f.model_dump()) for f in features]
        if (
            len(features) != snapshot.expected_plies
            or [f.ply for f in features] != list(range(1, len(features) + 1))
            or any(
                f.game_id != snapshot.source.game_id
                or f.feature_version != FEATURE_EXTRACTOR_VERSION
                or f.phase_classifier_version != PHASE_CLASSIFIER_VERSION
                for f in features
            )
        ):
            raise FeatureInputError("FEATURE_SET_INVALID")
        with self.sessions.begin() as s:
            # SQLite reservation serializes concurrent finalizers without changing source rows.
            s.execute(update(MoveFeature).where(MoveFeature.id == -1).values(id=-1))
            current = self._load(s, snapshot.source.game_id, snapshot.profile_hash)
            if current.input_hash != snapshot.input_hash:
                raise FeatureInputError("FEATURE_INPUT_CHANGED")
            s.execute(
                delete(MoveFeature).where(
                    MoveFeature.game_id == snapshot.source.game_id,
                    MoveFeature.feature_version == FEATURE_EXTRACTOR_VERSION,
                    MoveFeature.input_hash == snapshot.input_hash,
                )
            )
            for f in features:
                payload = f.model_dump(mode="json")
                s.add(
                    MoveFeature(
                        game_id=f.game_id,
                        ply=f.ply,
                        feature_version=f.feature_version,
                        phase_classifier_version=f.phase_classifier_version,
                        input_hash=snapshot.input_hash,
                        profile_hash=snapshot.profile_hash,
                        features_json=payload,
                        content_hash=fingerprint(payload),
                        **{k: getattr(f, k) for k in QUERY_FIELDS},
                    )
                )
