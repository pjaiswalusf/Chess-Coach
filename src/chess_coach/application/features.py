"""Offline feature batches: per-game atomic checkpoints, retry by missing snapshot."""

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from time import perf_counter
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from chess_coach.analytics.features import FeatureInputError, extract_game_features
from chess_coach.application.parse_imported_games import parse_game_with_source
from chess_coach.domain.feature_models import FEATURE_EXTRACTOR_VERSION
from chess_coach.infrastructure.persistence.feature_repository import FeatureRepository
from chess_coach.infrastructure.pgn.parser import parse_game

logger = logging.getLogger(__name__)


@dataclass
class FeatureSummary:
    run_id: str = field(default_factory=lambda: uuid4().hex)
    feature_version: int = FEATURE_EXTRACTOR_VERSION
    games_completed: int = 0
    games_skipped: int = 0
    games_failed: int = 0
    valid_moves: int = 0
    missing_clocks: int = 0
    missing_evaluations: int = 0
    mate_evaluations: int = 0
    clock_inconsistencies: int = 0
    extraction_seconds: float = 0
    persistence_seconds: float = 0
    reasons: dict[str, int] = field(default_factory=dict)


class ExtractFeatures:
    def __init__(
        self, store: FeatureRepository, checkpoint: Callable[[int], None] | None = None
    ):
        self.store, self.checkpoint = store, checkpoint

    def run(self, username: str, profile_hash: str) -> FeatureSummary:
        if not username.strip() or not profile_hash.strip():
            raise ValueError(
                "Supply a username and an explicit analysis profile (or 'board-only')."
            )
        summary = FeatureSummary()
        logger.info("feature_extraction_started", extra={"run_id": summary.run_id})
        for game_id in self.store.candidates(username):
            context = {
                "run_id": summary.run_id,
                "game_id": game_id,
                "feature_version": FEATURE_EXTRACTOR_VERSION,
            }
            try:
                snapshot = self.store.load(game_id, profile_hash)
                parsed, expected = parse_game_with_source(snapshot.source, parse_game)
                if parsed.total_plies != snapshot.expected_plies:
                    raise FeatureInputError("GAME_REVALIDATION_REQUIRED")
                if expected is not None and parsed.source_result != expected:
                    raise FeatureInputError("SOURCE_RESULT_MISMATCH")
                if (
                    parsed.white_username.casefold(),
                    parsed.black_username.casefold(),
                ) != (
                    snapshot.source.white_username.strip().casefold(),
                    snapshot.source.black_username.strip().casefold(),
                ):
                    raise FeatureInputError("SOURCE_PLAYER_MISMATCH")
                if expected:
                    parsed = replace(parsed, completion_provenance="chesscom_archive")
                if self.store.complete(snapshot, parsed.total_plies):
                    summary.games_skipped += 1
                    continue
                started = perf_counter()
                features = extract_game_features(game_id, parsed, snapshot.analyses)
                summary.extraction_seconds += perf_counter() - started
                started = perf_counter()
                self.store.save(snapshot, features)
                summary.persistence_seconds += perf_counter() - started
                summary.games_completed += 1
                summary.valid_moves += len(features)
                summary.missing_clocks += sum(
                    f.time_remaining_seconds is None for f in features
                )
                by_ply = {a.ply: a for a in snapshot.analyses}
                summary.missing_evaluations += sum(
                    f.ply not in by_ply
                    or (
                        by_ply[f.ply].eval_before_cp_white is None
                        and by_ply[f.ply].mate_before_white is None
                    )
                    for f in features
                )
                summary.mate_evaluations += sum(
                    a.mate_before_white is not None for a in snapshot.analyses
                )
                summary.clock_inconsistencies += sum(
                    "clock_inconsistent" in f.diagnostics for f in features
                )
                logger.info(
                    "feature_extraction_completed",
                    extra=context | {"plies": len(features)},
                )
            except (ValueError, SQLAlchemyError) as exc:
                code = (
                    exc.code
                    if isinstance(exc, FeatureInputError)
                    else "SCHEMA_INVALID"
                    if isinstance(exc, ValidationError)
                    else "PERSISTENCE_FAILED"
                    if isinstance(exc, SQLAlchemyError)
                    else "INPUT_INVALID"
                )
                summary.games_failed += 1
                summary.reasons[code] = summary.reasons.get(code, 0) + 1
                logger.warning(
                    "feature_extraction_failed",
                    extra=context | {"reason": code, "ply": getattr(exc, "ply", None)},
                )
                continue
            except Exception:
                logger.exception("feature_extraction_unexpected_failure", extra=context)
                raise
            if self.checkpoint:
                self.checkpoint(game_id)
        logger.info("feature_run_completed", extra={"summary": asdict(summary)})
        return summary
