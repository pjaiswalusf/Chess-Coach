"""Practice uses stored puzzle evidence and one short transaction per answer."""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Literal
from uuid import UUID

import chess
from pydantic import BaseModel
from sqlalchemy import select

from chess_coach.analytics.sample_policy import CRITICAL_LOSS_CP
from chess_coach.application.errors import OperationError
from chess_coach.domain.analysis import AnalysisProfile
from chess_coach.domain.game_records import PlayerColor
from chess_coach.domain.review_schedule import SCHEDULER_VERSION, schedule
from chess_coach.infrastructure.persistence.analysis_repository import (
    AnalysisRepository,
    profile_of,
)
from chess_coach.infrastructure.persistence.models import Puzzle, PuzzleAttempt, utc_now
from chess_coach.infrastructure.persistence.operations import reserve
from chess_coach.infrastructure.persistence.training_repository import (
    TrainingRepository,
)

logger = logging.getLogger(__name__)
MIN_TRANSFER_GAMES = 10
MIN_TRANSFER_MOVES = 100


class PublicPuzzle(BaseModel):
    id: int
    fen: str
    side_to_move: PlayerColor
    theme: str
    difficulty: str
    attempt_count: int
    legal_moves: list[str]
    solver_moves: int = 1


class NextPuzzle(BaseModel):
    puzzle: PublicPuzzle | None = None
    reason: Literal["NO_PUZZLES_DUE"] | None = None


class AttemptResult(BaseModel):
    attempt_id: int
    correct: bool
    submitted_move_uci: str
    solution_move_uci: str
    solution_san: str
    solution_pv_san: list[str]
    original_move_uci: str
    source_game_id: int
    source_ply: int
    source_profile_hash: str
    attempted_at: datetime
    next_review_at: datetime
    final_fen: str | None = None


class PuzzleContinuation(BaseModel):
    fen: str
    legal_moves: list[str]
    reply_san: str


class PuzzleStep(BaseModel):
    continuation: PuzzleContinuation | None = None
    result: AttemptResult | None = None


class ThemeStats(BaseModel):
    theme: str
    puzzles: int
    attempts: int
    correct: int
    accuracy: float | None


class TrainingStats(BaseModel):
    puzzles_total: int
    puzzles_attempted: int
    attempts_total: int
    correct_attempts: int
    incorrect_attempts: int
    accuracy: float | None
    puzzles_due: int
    average_attempts: float | None
    themes: list[ThemeStats]


class PeriodEvidence(BaseModel):
    game_ids: list[int]
    moves: int
    critical_errors: int
    errors_per_100: float | None


class TransferComparison(BaseModel):
    time_class: str
    time_control: str
    color: PlayerColor
    profile_hash: str
    analysis_version: str
    before: PeriodEvidence
    after: PeriodEvidence
    change_per_100: float | None
    relative_change_percent: float | None


class TransferReport(BaseModel):
    first_attempt_at: datetime | None = None
    min_games_per_period: int = MIN_TRANSFER_GAMES
    min_moves_per_period: int = MIN_TRANSFER_MOVES
    critical_loss_cp: int = CRITICAL_LOSS_CP
    cohorts: list[TransferComparison]


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


def _feedback(
    puzzle: Puzzle, attempt: PuzzleAttempt, board: chess.Board
) -> AttemptResult:
    try:
        if (
            not puzzle.solution_pv_json
            or puzzle.solution_pv_json[0] != puzzle.solution_uci
        ):
            raise ValueError("Inconsistent solution")
        pv = []
        final_fen = None
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


class TrainingService:
    def __init__(self, store: TrainingRepository):
        self.store = store

    def next(self, player_id: int | None, now: datetime) -> NextPuzzle:
        puzzle = self.store.next(player_id, now) if player_id is not None else None
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
    ) -> AttemptResult:
        step = self._submit(
            player_id, puzzle_id, submission_id, [uci], now, single=True
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
    ) -> PuzzleStep:
        return self._submit(player_id, puzzle_id, submission_id, moves, now)

    def _submit(
        self,
        player_id: int | None,
        puzzle_id: int,
        submission_id: UUID,
        moves: list[str],
        now: datetime,
        *,
        single: bool = False,
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
                if attempt is not None:
                    if (
                        attempt.submitted_line_json or [attempt.submitted_move_uci]
                    ) != moves:
                        raise OperationError(
                            "SUBMISSION_ID_CONFLICT",
                            "Use a fresh submission ID for a different move.",
                        )
                    duplicate = True
                else:
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
                    if puzzle.next_review_at > now:
                        raise OperationError(
                            "PUZZLE_NOT_DUE",
                            "This puzzle is scheduled for a later review. Load another puzzle.",
                        )
                    correct, following = _play_line(puzzle, board, moves)
                    if following is not None:
                        return PuzzleStep(continuation=following)
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
                feedback = _feedback(puzzle, attempt, board)
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
        )

    def transfer(self, player_id: int | None) -> TransferReport:
        if player_id is None:
            return TransferReport(cohorts=[])
        with self.store.sessions() as session:
            first = session.scalar(
                select(PuzzleAttempt.attempted_at)
                .join(Puzzle)
                .where(Puzzle.tracked_player_id == player_id)
                .order_by(PuzzleAttempt.attempted_at)
                .limit(1)
            )
            if first is None:
                return TransferReport(cohorts=[])
            evidence = session.execute(self.store.evidence(player_id))
            # Each game appears once per compatible profile. Track only scored
            # CP moves, with a denominator identical in both periods.
            by_cohort: dict[
                tuple[str, str, PlayerColor, str, str],
                dict[bool, dict[int, list[int]]],
            ] = defaultdict(lambda: defaultdict(dict))
            valid_games: dict[tuple[int, str], bool] = {}
            profiles: dict[int, AnalysisProfile] = {}
            for game, move, _, run in evidence:
                if (
                    not game.time_class
                    or not game.time_control
                    or move.loss_cp is None
                    or game.played_at == first
                ):
                    continue
                key = (game.id, move.profile_hash)
                if key not in valid_games:
                    if run.id not in profiles:
                        profiles[run.id] = profile_of(run)
                    profile = profiles[run.id]
                    valid_games[key] = (
                        profile.hash == move.profile_hash
                        and AnalysisRepository.compatible(session, game, profile)
                    )
                if not valid_games[key]:
                    continue
                cohort = (
                    game.time_class,
                    game.time_control,
                    game.player_color,
                    move.profile_hash,
                    move.analysis_version,
                )
                counts = by_cohort[cohort][game.played_at > first].setdefault(
                    game.id, [0, 0]
                )
                counts[0] += 1
                counts[1] += move.loss_cp >= CRITICAL_LOSS_CP
        return TransferReport(
            first_attempt_at=first,
            cohorts=[
                _compare(key, periods) for key, periods in sorted(by_cohort.items())
            ],
        )


def _compare(
    cohort: tuple[str, str, PlayerColor, str, str],
    periods: dict[bool, dict[int, list[int]]],
) -> TransferComparison:
    def period(games: dict[int, list[int]]) -> PeriodEvidence:
        moves = sum(counts[0] for counts in games.values())
        errors = sum(counts[1] for counts in games.values())
        sufficient = len(games) >= MIN_TRANSFER_GAMES and moves >= MIN_TRANSFER_MOVES
        return PeriodEvidence(
            game_ids=sorted(games),
            moves=moves,
            critical_errors=errors,
            errors_per_100=100 * errors / moves if sufficient else None,
        )

    before, after = period(periods.get(False, {})), period(periods.get(True, {}))
    baseline, subsequent = before.errors_per_100, after.errors_per_100
    change = (
        subsequent - baseline
        if baseline is not None and subsequent is not None
        else None
    )
    time_class, time_control, color, profile, version = cohort
    return TransferComparison(
        time_class=time_class,
        time_control=time_control,
        color=color,
        profile_hash=profile,
        analysis_version=version,
        before=before,
        after=after,
        change_per_100=change,
        relative_change_percent=100 * change / baseline
        if change is not None and baseline
        else None,
    )


def practice_counts(store: TrainingRepository) -> tuple[int, int]:
    with store.sessions() as session:
        rows = store.counts(session, None, utc_now())
        return sum(row[1] for row in rows), sum(row[5] for row in rows)
