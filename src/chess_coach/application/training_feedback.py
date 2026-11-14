"""Explain recorded puzzle attempts using saved engine evidence."""

import logging

import chess

from chess_coach.analytics.move_remarks import line_consequence
from chess_coach.application.errors import OperationError
from chess_coach.application.training_models import AttemptResult
from chess_coach.infrastructure.persistence.models import Puzzle, PuzzleAttempt

logger = logging.getLogger("chess_coach.application.training")


def _saved_rankings(evidence: dict[str, object], ply: int, fen: str) -> list[object]:
    if ply == 0:
        rankings = evidence.get("deep")
        return rankings if isinstance(rankings, list) else []
    continuation = evidence.get("continuation")
    followups = (
        continuation.get("followups")
        if isinstance(continuation, dict)
        else evidence.get("followups")
    )
    if isinstance(followups, list):
        for rankings in reversed(followups):
            if (
                isinstance(rankings, list)
                and rankings
                and isinstance(rankings[0], dict)
                and rankings[0].get("fen") == fen
            ):
                return rankings
    return []


def _describe_saved_reply(
    after: chess.Board, before: chess.Board, line: object, played_uci: str
) -> str | None:
    if not isinstance(line, (list, tuple)) or not line or line[0] != played_uci:
        return None
    try:
        return line_consequence(after, tuple(line[1:]), before)
    except ValueError:
        return None


def _explain_ranked_alternative(
    rankings: list[object], before: chess.Board, move: chess.Move, san: str
) -> str | None:
    if not rankings or not isinstance(best := rankings[0], dict):
        return None
    alternate = next(
        (
            entry
            for entry in rankings
            if isinstance(entry, dict) and entry.get("best_move_uci") == move.uci()
        ),
        None,
    )
    if alternate is None:
        return None
    if alternate.get("mate_winner") == (not before.turn):
        return f"{san} allows a forced mate."
    if best.get("mate_winner") == before.turn:
        if alternate.get("mate_winner") != before.turn:
            return f"{san} misses the forced mate."
        return f"{san} takes longer to force mate."
    best_cp = best.get("score_cp_white")
    alternate_cp = alternate.get("score_cp_white")
    if type(best_cp) is not int or type(alternate_cp) is not int:
        return None
    gap_cp = (best_cp - alternate_cp) * (1 if before.turn else -1)
    if gap_cp <= 0:
        return None
    detail = f"{san} gives up {gap_cp / 100:.2f} pawns of engine evaluation."
    after = before.copy()
    after.push(move)
    reply = _describe_saved_reply(after, before, alternate.get("pv_uci"), move.uci())
    return f"{detail} In the engine line, {reply}." if reply else detail


def _explain_wrong_move(
    puzzle: Puzzle, board: chess.Board, move: chess.Move, ply: int
) -> str:
    san = board.san(move)
    rankings = _saved_rankings(puzzle.verification_json, ply, board.fen())
    if reason := _explain_ranked_alternative(rankings, board, move, san):
        return reason
    after = board.copy()
    after.push(move)
    if after.is_stalemate():
        return f"{san} ends the game in stalemate."
    for reply in after.legal_moves:
        mate = after.copy()
        mate.push(reply)
        if mate.is_checkmate():
            return f"{san} allows checkmate in one with {after.san(reply)}."
    goal = {
        "forced_mate": "the verified mating line",
        "material_gain": "the verified sequence that wins material",
        "critical_capture": "the key capture in the verified line",
        "forcing_check": "the forcing check in the verified line",
    }.get(puzzle.theme, "the verified tactic")
    return f"{san} misses {goal}. Try another move in this position."


def build_attempt_feedback(
    puzzle: Puzzle, attempt: PuzzleAttempt, board: chess.Board
) -> AttemptResult:
    try:
        if (
            not puzzle.solution_pv_json
            or puzzle.solution_pv_json[0] != puzzle.solution_uci
        ):
            raise ValueError("Inconsistent solution")
        pv = []
        submitted = attempt.submitted_line_json or [attempt.submitted_move_uci]
        played_board = board.copy()
        final_ply = (len(submitted) - 1) * 2
        for uci in puzzle.solution_pv_json[:final_ply]:
            played_board.push_uci(uci)
        attempted_move = played_board.parse_uci(submitted[-1])
        reason = (
            None
            if attempt.is_correct
            else _explain_wrong_move(puzzle, played_board, attempted_move, final_ply)
        )
        played_board.push(attempted_move)
        final_fen = played_board.fen()
        for ply, uci in enumerate(puzzle.solution_pv_json, start=1):
            move = board.parse_uci(uci)
            if not move:
                raise ValueError("Null move in solution")
            pv.append(board.san(move))
            board.push(move)
            if (
                attempt.is_correct
                and puzzle.solve_plies > 1
                and ply == puzzle.solve_plies
            ):
                final_fen = board.fen()
    except ValueError as exc:
        logger.error("puzzle_invalid_solution", extra={"puzzle_id": puzzle.id})
        raise OperationError(
            "PUZZLE_DATA_INVALID", "Check the stored solution and backend logs.", 500
        ) from exc
    return AttemptResult(
        attempt_id=attempt.id,
        correct=attempt.is_correct,
        submitted_move_uci=attempt.submitted_move_uci,
        solution_move_uci=puzzle.solution_uci,
        solution_san=pv[0],
        solution_pv_san=pv,
        original_move_uci=puzzle.original_move_uci,
        source_game_id=puzzle.source_game_id,
        source_ply=puzzle.source_ply,
        source_profile_hash=puzzle.source_profile_hash,
        attempted_at=attempt.attempted_at,
        next_review_at=attempt.next_review_at_after,
        final_fen=final_fen,
        wrong_move_reason=reason,
        last_move_uci=(
            puzzle.solution_pv_json[puzzle.solve_plies - 1]
            if attempt.is_correct
            else submitted[-1]
        ),
    )
