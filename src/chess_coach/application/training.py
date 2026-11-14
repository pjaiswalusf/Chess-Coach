"""Practice uses stored puzzle evidence and one short transaction per answer."""

import logging
from datetime import datetime
from uuid import UUID

import chess
from sqlalchemy import select
from sqlalchemy.orm import Session

from chess_coach.application.errors import OperationError
from chess_coach.application.training_feedback import build_attempt_feedback
from chess_coach.application.training_models import (
    AttemptResult,
    NextPuzzle,
    PublicPuzzle,
    PuzzleContinuation,
    PuzzleStep,
    ThemeStats,
    TrainingStats,
)
from chess_coach.application.training_transfer import (
    TransferReport,
    build_transfer_report,
)
from chess_coach.domain.review_schedule import SCHEDULER_VERSION, schedule
from chess_coach.infrastructure.persistence.models import Puzzle, PuzzleAttempt, utc_now
from chess_coach.infrastructure.persistence.operations import reserve
from chess_coach.infrastructure.persistence.training_repository import (
    TrainingRepository,
)

logger = logging.getLogger(__name__)


def _puzzle_board(puzzle: Puzzle) -> chess.Board:
    try:
        board = chess.Board(puzzle.fen)
        if board.is_valid() and board.turn == (puzzle.side_to_move == "white"):
            return board
    except ValueError:
        pass
    logger.error("puzzle_invalid_position", extra={"puzzle_id": puzzle.id})
    raise OperationError(
        "PUZZLE_DATA_INVALID", "Check the stored puzzle and backend logs.", 500
    )


def _play_line(
    puzzle: Puzzle, board: chess.Board, moves: list[str]
) -> tuple[bool, PuzzleContinuation | None]:
    if not 1 <= puzzle.solve_plies <= len(puzzle.solution_pv_json) or (
        puzzle.solution_pv_json[0] != puzzle.solution_uci
    ):
        raise OperationError(
            "PUZZLE_DATA_INVALID", "Check the stored solution and backend logs.", 500
        )
    replay = board.copy(stack=False)
    for index, uci in enumerate(moves):
        ply = index * 2
        if ply >= puzzle.solve_plies:
            raise OperationError(
                "INVALID_SEQUENCE", "Submit only the requested moves.", 422
            )
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            raise OperationError(
                "INVALID_MOVE", "Submit a move in UCI notation.", 422
            ) from None
        if move not in replay.legal_moves:
            raise OperationError(
                "ILLEGAL_MOVE", "Choose a legal move in this position.", 422
            )
        last = index == len(moves) - 1
        if uci != puzzle.solution_pv_json[ply]:
            if last:
                return False, None
            raise OperationError(
                "INVALID_SEQUENCE", "Replay the puzzle from its starting position.", 422
            )
        if ply + 2 >= puzzle.solve_plies:
            if last:
                return True, None
            raise OperationError(
                "INVALID_SEQUENCE", "Submit only the requested moves.", 422
            )
        replay.push(move)
        try:
            reply = replay.parse_uci(puzzle.solution_pv_json[ply + 1])
            if not reply:
                raise ValueError("Null move")
            san = replay.san(reply)
            replay.push(reply)
        except ValueError as exc:
            raise OperationError(
                "PUZZLE_DATA_INVALID",
                "Check the stored solution and backend logs.",
                500,
            ) from exc
        if last:
            return True, PuzzleContinuation(
                fen=replay.fen(),
                legal_moves=sorted(candidate.uci() for candidate in replay.legal_moves),
                reply_san=san,
            )
    raise OperationError("INVALID_SEQUENCE", "Submit at least one move.", 422)


def _check_attempt_allowed(
    session: Session,
    puzzle: Puzzle,
    now: datetime,
    single: bool,
    retry_after_attempt_id: int | None,
) -> None:
    if single and puzzle.solve_plies > 1:
        raise OperationError(
            "PUZZLE_REQUIRES_SEQUENCE",
            "Reload Training to play the full puzzle.",
            422,
        )
    if puzzle.status != "active":
        raise OperationError(
            "PUZZLE_RETIRED",
            "This puzzle is retired. Load another puzzle.",
        )
    can_retry = False
    if retry_after_attempt_id is not None:
        last_attempt = session.scalar(
            select(PuzzleAttempt)
            .where(PuzzleAttempt.puzzle_id == puzzle.id)
            .order_by(PuzzleAttempt.id.desc())
            .limit(1)
        )
        can_retry = bool(
            last_attempt
            and last_attempt.id == retry_after_attempt_id
            and not last_attempt.is_correct
        )
    if puzzle.next_review_at > now and not can_retry:
        raise OperationError(
            "PUZZLE_NOT_DUE",
            "This puzzle is scheduled for a later review. Load another puzzle.",
        )


def _record_attempt(
    session: Session,
    puzzle: Puzzle,
    submission_id: UUID,
    moves: list[str],
    correct: bool,
    now: datetime,
) -> PuzzleAttempt:
    streak, next_review = schedule(now, puzzle.correct_streak, correct)
    attempt = PuzzleAttempt(
        puzzle_id=puzzle.id,
        submission_id=str(submission_id),
        submitted_move_uci=moves[0],
        submitted_line_json=moves if len(moves) > 1 else None,
        is_correct=correct,
        attempted_at=now,
        next_review_at_after=next_review,
        scheduler_version=SCHEDULER_VERSION,
    )
    session.add(attempt)
    session.flush()
    puzzle.attempt_count += 1
    puzzle.correct_streak = streak
    puzzle.next_review_at = next_review
    puzzle.last_attempt_at = now
    return attempt


class TrainingService:
    def __init__(self, store: TrainingRepository):
        self.store = store

    def next(
        self, player_id: int | None, now: datetime, puzzle_id: int | None = None
    ) -> NextPuzzle:
        puzzle = (
            self.store.next(player_id, now, puzzle_id)
            if player_id is not None
            else None
        )
        if puzzle is None:
            return NextPuzzle(reason="NO_PUZZLES_DUE")
        board = _puzzle_board(puzzle)
        return NextPuzzle(
            puzzle=PublicPuzzle(
                id=puzzle.id,
                fen=puzzle.fen,
                side_to_move=puzzle.side_to_move,
                theme=puzzle.theme,
                difficulty=puzzle.difficulty,
                attempt_count=puzzle.attempt_count,
                legal_moves=sorted(move.uci() for move in board.legal_moves),
                solver_moves=(puzzle.solve_plies + 1) // 2,
            )
        )

    def submit(
        self,
        player_id: int | None,
        puzzle_id: int,
        submission_id: UUID,
        uci: str,
        now: datetime,
        retry_after_attempt_id: int | None = None,
    ) -> AttemptResult:
        step = self._submit(
            player_id,
            puzzle_id,
            submission_id,
            [uci],
            now,
            single=True,
            retry_after_attempt_id=retry_after_attempt_id,
        )
        assert step.result is not None
        return step.result

    def play(
        self,
        player_id: int | None,
        puzzle_id: int,
        submission_id: UUID,
        moves: list[str],
        now: datetime,
        retry_after_attempt_id: int | None = None,
    ) -> PuzzleStep:
        return self._submit(
            player_id,
            puzzle_id,
            submission_id,
            moves,
            now,
            retry_after_attempt_id=retry_after_attempt_id,
        )

    def _submit(
        self,
        player_id: int | None,
        puzzle_id: int,
        submission_id: UUID,
        moves: list[str],
        now: datetime,
        *,
        single: bool = False,
        retry_after_attempt_id: int | None = None,
    ) -> PuzzleStep:
        context = {"puzzle_id": puzzle_id}
        duplicate = False
        try:
            with self.store.sessions.begin() as session:
                reserve(session)
                puzzle = session.get(Puzzle, puzzle_id)
                if puzzle is None or puzzle.tracked_player_id != player_id:
                    raise OperationError(
                        "PUZZLE_NOT_FOUND", "Choose a current training puzzle.", 404
                    )
                attempt = session.scalar(
                    select(PuzzleAttempt).where(
                        PuzzleAttempt.puzzle_id == puzzle_id,
                        PuzzleAttempt.submission_id == str(submission_id),
                    )
                )
                board = _puzzle_board(puzzle)
                duplicate = attempt is not None
                if attempt is None:
                    _check_attempt_allowed(
                        session, puzzle, now, single, retry_after_attempt_id
                    )
                    correct, following = _play_line(puzzle, board, moves)
                    if following is not None:
                        return PuzzleStep(continuation=following)
                    attempt = _record_attempt(
                        session, puzzle, submission_id, moves, correct, now
                    )
                elif (
                    attempt.submitted_line_json or [attempt.submitted_move_uci]
                ) != moves:
                    raise OperationError(
                        "SUBMISSION_ID_CONFLICT",
                        "Use a fresh submission ID for a different move.",
                    )
                feedback = build_attempt_feedback(puzzle, attempt, board)
        except OperationError as exc:
            logger.info(
                "puzzle_attempt_rejected", extra={**context, "error_code": exc.code}
            )
            raise
        logger.info(
            "puzzle_attempt_duplicate" if duplicate else "puzzle_attempt_accepted",
            extra=context,
        )
        if not duplicate:
            logger.info(
                "puzzle_review_scheduled",
                extra={
                    **context,
                    "next_review_at": feedback.next_review_at.isoformat(),
                },
            )
        return PuzzleStep(result=feedback)

    def stats(self, player_id: int | None, now: datetime) -> TrainingStats:
        with self.store.sessions() as session:
            rows = (
                self.store.counts(session, player_id, now)
                if player_id is not None
                else []
            )
            streak = (
                self.store.solve_streak(session, player_id)
                if player_id is not None
                else 0
            )
        puzzles = attempted = attempts = correct = due = 0
        themes = []
        for theme, count, tried, answers, right, ready in rows:
            puzzles += count
            attempted += tried
            attempts += answers
            correct += right
            due += ready
            themes.append(
                ThemeStats(
                    theme=theme,
                    puzzles=count,
                    attempts=answers,
                    correct=right,
                    accuracy=right / answers if answers else None,
                )
            )
        return TrainingStats(
            puzzles_total=puzzles,
            puzzles_attempted=attempted,
            attempts_total=attempts,
            correct_attempts=correct,
            incorrect_attempts=attempts - correct,
            accuracy=correct / attempts if attempts else None,
            puzzles_due=due,
            average_attempts=attempts / attempted if attempted else None,
            themes=themes,
            solve_streak=streak,
        )

    def transfer(self, player_id: int | None) -> TransferReport:
        return build_transfer_report(self.store, player_id)


def practice_counts(store: TrainingRepository) -> tuple[int, int]:
    with store.sessions() as session:
        rows = store.counts(session, None, utc_now())
        return sum(row[1] for row in rows), sum(row[5] for row in rows)
