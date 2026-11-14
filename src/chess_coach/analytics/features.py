"""Pure extraction from completed parsed games and existing optional evidence."""

from collections.abc import Sequence

import chess

from chess_coach.analytics.clocks import ClockState
from chess_coach.analytics.feature_config import (
    DEFAULT_CONFIG,
)
from chess_coach.analytics.phases import classify_phase
from chess_coach.domain.feature_models import FeatureAnalysis, GamePhase, MoveFeatures
from chess_coach.domain.game_records import ParsedGame, PlayerColor
from chess_coach.domain.material import PIECE_VALUES, calculate_material


class FeatureInputError(ValueError):
    def __init__(self, code: str, ply: int | None = None):
        self.code, self.ply = code, ply
        super().__init__(f"{code}: inspect stored game/evidence and retry (ply={ply}).")


def tactical(board: chess.Board, move: chess.Move) -> tuple[bool, bool, bool]:
    if move not in board.legal_moves:
        raise FeatureInputError("INVALID_BEST_MOVE", len(board.move_stack) + 1)
    after = board.copy(stack=False)
    after.push(move)
    return board.is_capture(move), board.gives_check(move), after.is_checkmate()


def _score(
    evidence: FeatureAnalysis, side: str
) -> tuple[int | None, int | None, bool | None]:
    return (
        getattr(evidence, f"eval_{side}_cp_white"),
        getattr(evidence, f"mate_{side}_white"),
        getattr(evidence, f"mate_{side}_winner"),
    )


def _validate_score(
    board: chess.Board, evidence: FeatureAnalysis, side: str, ply: int
) -> None:
    cp, mate, winner = _score(evidence, side)
    if cp is None and mate is None:
        return
    outcome = board.outcome(claim_draw=False)
    if outcome is None:
        valid = mate != 0
    elif outcome.winner is None:
        valid = cp == 0 and mate is None
    else:
        valid = mate == 0 and winner == outcome.winner
    if not valid:
        raise FeatureInputError("SCORE_POSITION_CONFLICT", ply)


def extract_game_features(
    game_id: int,
    game: ParsedGame,
    analyses: Sequence[FeatureAnalysis] = (),
) -> list[MoveFeatures]:
    config = DEFAULT_CONFIG
    if game_id < 1 or game.source_result not in {"1-0", "0-1", "1/2-1/2"}:
        raise FeatureInputError("INVALID_COMPLETED_GAME")
    board = chess.Board(game.initial_fen)
    if not board.is_valid() or (
        not game.history_before_start_unknown and board.fen() != chess.STARTING_FEN
    ):
        raise FeatureInputError("INVALID_STARTING_HISTORY")
    analysis = {a.ply: a for a in analyses}
    if len(analysis) != len(analyses) or any(p > game.total_plies for p in analysis):
        raise FeatureInputError("INVALID_ANALYSIS_PLIES")
    # Track original minor identities only when the full starting history is known.
    originals = (
        {
            s: (s, 0)
            for s, p in board.piece_map().items()
            if p.piece_type in (chess.KNIGHT, chess.BISHOP)
        }
        if not game.history_before_start_unknown
        else {}
    )
    castling: dict[bool, tuple[str, int] | None] = {True: None, False: None}
    clocks = ClockState.for_game(game)
    phase: GamePhase | None = None
    previous_capture_square = None
    previous_eval: int | None = None
    result = []
    for ply, parsed in enumerate(game.moves, 1):
        mover = PlayerColor.WHITE if board.turn else PlayerColor.BLACK
        try:
            move = chess.Move.from_uci(parsed.uci)
        except ValueError:
            raise FeatureInputError("INVALID_PLAYED_MOVE", ply) from None
        if (
            parsed.ply_index != ply
            or parsed.fen_before != board.fen()
            or parsed.mover_color != mover
            or parsed.move_number != board.fullmove_number
        ):
            raise FeatureInputError("FEN_ALIGNMENT_FAILED", ply)
        if move not in board.legal_moves or board.is_game_over(claim_draw=False):
            raise FeatureInputError("INVALID_PLAYED_MOVE", ply)
        evidence = analysis.get(ply)
        if evidence and (
            evidence.fen_before != board.fen() or evidence.played_move_uci != parsed.uci
        ):
            raise FeatureInputError("ANALYSIS_ALIGNMENT_FAILED", ply)
        if evidence:
            _validate_score(board, evidence, "before", ply)
            prior = analysis.get(ply - 1)
            if prior:
                previous_score, current_score = (
                    _score(prior, "after"),
                    _score(evidence, "before"),
                )
                if (
                    any(v is not None for v in previous_score)
                    and any(v is not None for v in current_score)
                    and previous_score != current_score
                ):
                    raise FeatureInputError("ADJACENT_SCORE_CONFLICT", ply)
        best: tuple[bool | None, bool | None, bool | None] = (None, None, None)
        if evidence and evidence.best_move_uci is not None:
            try:
                best = tactical(board, chess.Move.from_uci(evidence.best_move_uci))
            except ValueError:
                raise FeatureInputError("INVALID_BEST_MOVE", ply) from None
        turn, number = board.turn, board.fullmove_number
        piece = board.piece_at(move.from_square)
        assert piece is not None
        capture, check, mate = tactical(board, move)
        castle = board.is_castling(move)
        captured = (
            chess.PAWN
            if board.is_en_passant(move)
            else board.piece_type_at(move.to_square)
            if capture
            else None
        )
        white_before, black_before = calculate_material(board)
        phase, reason, non_pawn = classify_phase(
            board,
            phase,
            unknown_history=game.history_before_start_unknown,
            config=config,
        )
        original = originals.pop(move.from_square, None)
        originals.pop(move.to_square, None)
        repeat = (
            None
            if game.history_before_start_unknown
            else bool(original and original[1] > 0 and phase == GamePhase.OPENING)
        )
        if original:
            originals[move.to_square] = (original[0], original[1] + 1)
        if castle:
            castling[turn] = (
                "kingside"
                if chess.square_file(move.to_square)
                > chess.square_file(move.from_square)
                else "queenside",
                number,
            )
        early_queen = (
            piece.piece_type == chess.QUEEN and number <= config.opening_last_move
        )
        board.push(move)
        if board.fen() != parsed.fen_after:
            raise FeatureInputError("FEN_ALIGNMENT_FAILED", ply)
        if evidence:
            _validate_score(board, evidence, "after", ply)
        white_after, black_after = calculate_material(board)
        sign = 1 if turn else -1
        balance_before, balance_after = (
            sign * (white_before - black_before),
            sign * (white_after - black_after),
        )
        player_sign = 1 if game.player_color == PlayerColor.WHITE else -1
        before = (
            evidence.eval_before_cp_white * player_sign
            if evidence and evidence.eval_before_cp_white is not None
            else None
        )
        after = (
            evidence.eval_after_cp_white * player_sign
            if evidence and evidence.eval_after_cp_white is not None
            else None
        )
        band = (
            None
            if before is None
            else "large_advantage"
            if before >= config.advantage_cp
            else "large_disadvantage"
            if before <= -config.advantage_cp
            else "approximately_equal"
        )
        recapture = capture and previous_capture_square == move.to_square
        timing = clocks.observe(parsed, config)
        quick = timing["move_played_quickly"]
        critical = evidence.is_critical_error if evidence else None
        castle_info = castling[turn]
        king = board.king(turn)
        assert king is not None
        payload = dict(
            game_id=game_id,
            ply=ply,
            mover=mover,
            tracked_player=game.player_color,
            phase=phase,
            phase_reason=reason,
            non_pawn_material=non_pawn,
            played_is_capture=capture,
            played_gives_check=check,
            played_is_castling=castle,
            played_mates_immediately=mate,
            best_is_capture=best[0],
            best_gives_check=best[1],
            best_mates_immediately=best[2],
            captured_piece_type=chess.piece_name(captured) if captured else None,
            captured_piece_value=PIECE_VALUES[captured] if captured else 0,
            white_material_before=white_before,
            black_material_before=black_before,
            white_material_after=white_after,
            black_material_after=black_after,
            material_balance_before=balance_before,
            material_balance_after=balance_after,
            material_balance_change=balance_after - balance_before,
            engine_advantage_before=band,
            advantage_lost=(
                before >= config.advantage_cp and after <= config.lost_advantage_cp
            )
            if before is not None and after is not None
            else None,
            advantage_created_after_opponent_move=(
                mover != game.player_color and before < config.advantage_cp <= after
            )
            if before is not None and after is not None
            else None,
            player_preserved_existing_advantage=(
                mover == game.player_color
                and before >= config.advantage_cp
                and after >= config.advantage_cp
            )
            if before is not None and after is not None
            else None,
            immediate_recapture_observed=recapture,
            player_had_advantage_before_exchange=(previous_eval >= config.advantage_cp)
            if recapture and previous_eval is not None
            else None,
            queen_moved_early=early_queen,
            minor_pieces_on_starting_squares=None
            if game.history_before_start_unknown
            else sum(
                square == origin and board.color_at(square) == turn
                for square, (origin, _) in originals.items()
            ),
            minor_piece_repeated_move=repeat,
            has_castled=True
            if castle_info
            else None
            if game.history_before_start_unknown
            else False,
            castling_side=castle_info[0] if castle_info else None,
            castling_move_number=castle_info[1] if castle_info else None,
            king_on_central_file=chess.square_file(king) in (3, 4),
            critical_error_on_fast_move=bool(critical and quick)
            if critical is not None and quick is not None
            else None,
            **timing,
        )
        result.append(MoveFeatures.model_validate(payload))
        previous_capture_square = move.to_square if capture else None
        previous_eval = before
    if board.fen() != game.final_fen:
        raise FeatureInputError("FINAL_FEN_MISMATCH")
    outcome = board.outcome(claim_draw=False)
    if outcome and outcome.result() != game.source_result:
        raise FeatureInputError("RESULT_MISMATCH")
    return result
