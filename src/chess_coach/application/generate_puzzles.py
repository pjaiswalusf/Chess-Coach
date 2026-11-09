"""Generate bounded batches from existing completed historical analysis."""

import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Protocol

import chess
from sqlalchemy.exc import SQLAlchemyError

from chess_coach.application.analysis import configured_profile
from chess_coach.application.errors import OperationError
from chess_coach.application.parse_imported_games import ParseInput, _source_result
from chess_coach.config import Settings
from chess_coach.domain.analysis import (
    DRAW_POLICY,
    fingerprint,
    history_hash,
    validate_result,
)
from chess_coach.domain.engine_types import EngineResult
from chess_coach.domain.game_records import PGNParseError
from chess_coach.domain.score_utils import calculate_loss_cp
from chess_coach.domain.training import (
    GENERATOR_VERSION,
    POLICY,
    Rejected,
    Rejection,
    verify_solution,
)
from chess_coach.infrastructure.engine.exceptions import (
    EngineAnalysisError,
    EngineUnavailableError,
    InvalidPositionError,
    UnstablePuzzleEvidenceError,
)
from chess_coach.infrastructure.persistence.analysis_repository import (
    profile_of,
    result_of,
    source_hash,
)
from chess_coach.infrastructure.persistence.models import utc_now
from chess_coach.infrastructure.persistence.training_repository import (
    Candidate,
    TrainingRepository,
)
from chess_coach.infrastructure.pgn.parser import parse_game

logger = logging.getLogger(__name__)


class VerificationEngine(Protocol):
    engine_name: str

    def start(self) -> None: ...
    def close(self) -> None: ...
    def analyze_puzzle_candidate(
        self, board: chess.Board, *, nodes: int, multipv: int
    ) -> list[EngineResult]: ...


def reconstruct(candidate: Candidate, username: str, max_bytes: int) -> chess.Board:
    game, move, state, run = candidate
    if (
        state.source_hash != source_hash(game)
        or profile_of(run).hash != move.profile_hash
    ):
        raise Rejected(Rejection.MISSING_ANALYSIS)
    try:
        expected, final_fen = _source_result(
            ParseInput(
                game.id,
                game.raw_pgn,
                username,
                game.platform,
                game.white_username,
                game.black_username,
                game.source_evidence,
            )
        )
        parsed = parse_game(
            game.raw_pgn, username, max_bytes=max_bytes, source_final_fen=final_fen
        )
    except PGNParseError as exc:
        raise Rejected(Rejection.INVALID_POSITION) from exc
    if (
        (expected is not None and parsed.source_result != expected)
        or parsed.player_result != game.result
        or parsed.white_username.casefold() != game.white_username.casefold()
        or parsed.black_username.casefold() != game.black_username.casefold()
        or parsed.history_before_start_unknown
    ):
        raise Rejected(Rejection.UNSUPPORTED_GAME)
    if parsed.player_color != game.player_color or move.mover != parsed.player_color:
        raise Rejected(Rejection.WRONG_PLAYER_TURN)
    if not 1 <= move.ply <= parsed.total_plies:
        raise Rejected(Rejection.INVALID_POSITION)
    if not state.position_ids or len(state.position_ids) != parsed.total_plies + 1:
        raise Rejected(Rejection.MISSING_ANALYSIS)

    board = chess.Board(parsed.initial_fen)
    try:
        for previous in parsed.moves[: move.ply - 1]:
            board.push_uci(previous.uci)
        played = board.parse_uci(move.played_move_uci)
    except ValueError as exc:
        raise Rejected(Rejection.INVALID_POSITION) from exc
    if board.turn != (parsed.player_color == "white"):
        raise Rejected(Rejection.WRONG_PLAYER_TURN)
    if (
        not board.is_valid()
        or board.fen() != move.fen_before
        or played.uci() != parsed.moves[move.ply - 1].uci
        or board.is_game_over(claim_draw=True)
    ):
        raise Rejected(Rejection.INVALID_POSITION)
    if board.legal_moves.count() < POLICY.min_legal_moves:
        raise Rejected(Rejection.INSUFFICIENT_TACTICAL_VALUE)
    return board


def validate_source_analysis(
    store: TrainingRepository, candidate: Candidate, board: chess.Board
) -> None:
    _, move, state, run = candidate
    positions = store.source_positions(state, move.ply)
    if positions is None:
        raise Rejected(Rejection.MISSING_ANALYSIS)
    profile = profile_of(run)
    cursor = board.copy(stack=True)
    for index, position in enumerate(positions):
        if index:
            cursor.push_uci(move.played_move_uci)
        if (
            position.engine_version != profile.engine
            or position.analysis_version != profile.version
            or position.config_hash != profile.config_hash
            or position.draw_policy_version != profile.draw_policy
            or position.initial_fen != cursor.root().fen()
            or position.moves_uci_json != [m.uci() for m in cursor.move_stack]
            or position.history_before_start_unknown
            or position.history_hash != history_hash(cursor, False)
        ):
            raise Rejected(Rejection.MISSING_ANALYSIS)
        try:
            validate_result(cursor, result_of(position), profile.engine)
        except ValueError as exc:
            raise Rejected(Rejection.MISSING_ANALYSIS) from exc
    before, after = positions
    loss = (
        calculate_loss_cp(before.score_cp_white, after.score_cp_white, board.turn)
        if before.score_cp_white is not None and after.score_cp_white is not None
        else None
    )
    if (
        (move.eval_before_cp_white, move.mate_before_white, move.mate_before_winner)
        != (before.score_cp_white, before.mate_distance_white, before.mate_winner)
        or (move.eval_after_cp_white, move.mate_after_white, move.mate_after_winner)
        != (after.score_cp_white, after.mate_distance_white, after.mate_winner)
        or move.loss_cp != loss
        or move.best_move_uci != before.best_move_uci
        or move.pv_json != before.pv_json
    ):
        raise Rejected(Rejection.MISSING_ANALYSIS)


@dataclass
class GenerationReport:
    next_after_move_id: int
    candidates_examined: int = 0
    accepted: int = 0
    already_existing: int = 0
    rejected: int = 0
    errors: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    retry_from_move_id: int | None = None
    error: str | None = None


def generate_puzzles(
    store: TrainingRepository,
    engine: VerificationEngine,
    settings: Settings,
    player_id: int,
    profile: str,
    after: int = 0,
    limit: int | None = None,
) -> GenerationReport:
    limit = settings.training_candidate_limit if limit is None else limit
    if not 1 <= limit <= settings.training_candidate_limit or after < 0:
        raise ValueError(
            "Choose a positive limit within the configured cap and a nonnegative cursor."
        )
    nodes = min(settings.training_verification_nodes, settings.stockfish_max_nodes)
    if nodes < 4:
        raise ValueError(
            "Training verification requires a Stockfish node ceiling of at least 4."
        )
    username, candidates = store.candidates(player_id, profile, after, limit)
    report = GenerationReport(after)
    reasons: Counter[str] = Counter()
    logger.info("puzzle_generation_started", extra={"tracked_player_id": player_id})
    started = False
    try:
        for candidate in candidates:
            game, move, _, run = candidate
            report.candidates_examined += 1
            event = {"source_game_id": game.id, "run_id": run.id, "ply": move.ply}
            try:
                if store.exists(player_id, game.id, move.ply):
                    report.already_existing += 1
                else:
                    board = reconstruct(candidate, username, settings.pgn_max_bytes)
                    validate_source_analysis(store, candidate, board)
                    if not started:
                        engine.start()
                        started = True
                    ranks = min(POLICY.multipv, board.legal_moves.count())
                    shallow = engine.analyze_puzzle_candidate(
                        board, nodes=nodes // 4, multipv=ranks
                    )
                    first = verify_solution(
                        board, move.played_move_uci, shallow, engine.engine_name
                    )
                    deep = engine.analyze_puzzle_candidate(
                        board, nodes=nodes, multipv=ranks
                    )
                    solution = verify_solution(
                        board, move.played_move_uci, deep, engine.engine_name
                    )
                    if (solution.move_uci, solution.theme) != (
                        first.move_uci,
                        first.theme,
                    ):
                        raise Rejected(Rejection.UNSTABLE_ENGINE_RESULT)
                    config = {
                        **configured_profile(settings, engine.engine_name).config,
                        "nodes": nodes,
                        "stability_nodes": nodes // 4,
                        "multipv": ranks,
                        "draw_policy": DRAW_POLICY,
                        "claimable_draws": "reject_candidate",
                        "policy": asdict(POLICY),
                    }
                    now = utc_now()
                    puzzle_id = store.publish(
                        {
                            "tracked_player_id": player_id,
                            "source_game_id": game.id,
                            "source_ply": move.ply,
                            "source_analysis_version": move.analysis_version,
                            "source_profile_hash": profile,
                            "fen": board.fen(),
                            "side_to_move": game.player_color,
                            "original_move_uci": move.played_move_uci,
                            "solution_uci": solution.move_uci,
                            "solution_pv_json": list(solution.pv),
                            "theme": solution.theme,
                            "difficulty": solution.difficulty,
                            "engine_version": engine.engine_name,
                            "engine_config_hash": fingerprint(config),
                            "verification_json": {
                                "config": config,
                                "history_hash": history_hash(board, False),
                                "source_hash": source_hash(game),
                                "shallow": [asdict(line) for line in shallow],
                                "deep": [asdict(line) for line in deep],
                            },
                            "generator_version": GENERATOR_VERSION,
                            "next_review_at": now,
                            "created_at": now,
                        }
                    )
                    if puzzle_id is None:
                        report.already_existing += 1
                    else:
                        report.accepted += 1
                        logger.info(
                            "puzzle_created", extra={**event, "puzzle_id": puzzle_id}
                        )
            except Rejected as exc:
                reasons[exc.reason] += 1
                report.rejected += 1
                logger.info(
                    "puzzle_candidate_rejected",
                    extra={**event, "rejection_reason": exc.reason},
                )
            except (InvalidPositionError, UnstablePuzzleEvidenceError) as exc:
                reason = (
                    Rejection.UNSTABLE_ENGINE_RESULT
                    if isinstance(exc, UnstablePuzzleEvidenceError)
                    else Rejection.INVALID_POSITION
                )
                reasons[reason] += 1
                report.rejected += 1
                logger.info(
                    "puzzle_candidate_rejected",
                    extra={**event, "rejection_reason": reason},
                )
            except (
                EngineAnalysisError,
                EngineUnavailableError,
                SQLAlchemyError,
            ) as exc:
                report.errors += 1
                if report.retry_from_move_id is None:
                    report.retry_from_move_id = report.next_after_move_id
                logger.exception("puzzle_generation_failed", extra=event)
                if isinstance(exc, (EngineAnalysisError, EngineUnavailableError)):
                    report.error = "Stockfish verification failed. Check the engine and retry from retry_from_move_id."
                    break
                report.error = "A puzzle write failed. Check database access and retry from retry_from_move_id."
            report.next_after_move_id = move.id
    finally:
        if started:
            try:
                engine.close()
            except EngineAnalysisError:
                logger.exception("puzzle_engine_shutdown_failed")
                report.error = "Stockfish shutdown failed. Check the local engine process before retrying."
                report.errors += 1
    report.rejection_reasons = dict(sorted(reasons.items()))
    return report


def guard_idle(store: TrainingRepository) -> None:
    from sqlalchemy import select

    from chess_coach.domain.analysis import ACTIVE
    from chess_coach.infrastructure.persistence.models import AnalysisRun

    with store.sessions() as session:
        if session.scalar(
            select(AnalysisRun.id).where(AnalysisRun.status.in_(ACTIVE)).limit(1)
        ):
            raise OperationError(
                "ANALYSIS_ALREADY_RUNNING",
                "Finish or cancel the queued analysis before generating puzzles.",
            )
