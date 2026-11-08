"""Explicit one-time Stockfish snapshot builder; never run by tests.

uv run python scripts/build_coaching_dataset.py
"""

import json
from pathlib import Path

import chess

from chess_coach.analytics.phases import classify_phase
from chess_coach.application.analysis import configured_profile
from chess_coach.config import Settings
from chess_coach.domain.analysis import fingerprint
from chess_coach.domain.coaching_models import EngineScore, MoveCoachingEvidence
from chess_coach.domain.score_utils import calculate_loss_cp
from chess_coach.infrastructure.engine.stockfish_adapter import StockfishAdapter

# Synthetic completed-game declarations, with legal moves from conventional play.
# No claim of historical human provenance or human-reviewed tactical themes.
LINE = "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O h3 Nb8 d4 Nbd7 c4 c6 cxb5 axb5 Nc3 Bb7 Bg5 b4 Nb1 h6 Bh4 c5 d5 Nb6 Nbd2 Nh7 Bxe7 Qxe7 a3 bxa3 Rxa3 Rxa3 bxa3 f5"
END_FENS = [
    "8/8/4k3/8/4K3/8/4P3/8 w - - 0 40",
    "8/4p3/8/4k3/8/4K3/8/8 b - - 0 40",
]
MATES = [
    (chess.STARTING_FEN, "f3 e5 g4"),
    (chess.STARTING_FEN, "e4 e5 Bc4 Nc6 Qh5 Nf6"),
]


def main():
    settings = Settings(_env_file=None)
    candidates = []
    board = chess.Board()
    for index, san in enumerate(LINE.split()):
        played = board.parse_san(san)
        if index < 8 or 20 <= index < 36 or 8 <= index < 16:
            category = (
                "opening"
                if index < 8
                else "insufficient"
                if index < 16
                else "middlegame"
            )
            candidates.append((category, board.copy(stack=True), played))
        board.push(played)
    for fen in END_FENS:
        board = chess.Board(fen)
        for _ in range(5):
            move = next(m for m in board.legal_moves if not board.is_capture(m))
            candidates.append(("endgame", board.copy(stack=True), move))
            board.push(move)
    for _, sans in MATES:
        board = chess.Board()
        for san in sans.split():
            board.push_san(san)
        # Multiple legal alternatives near a known mating threat, not duplicated positions/moves.
        for move in list(board.legal_moves)[:4]:
            candidates.append(("mate_related", board.copy(stack=True), move))
    rows = []
    with StockfishAdapter(settings) as engine:
        profile = configured_profile(settings, engine.engine_name)
        for i, (category, board, played) in enumerate(candidates, 1):
            before = engine.analyze(board)
            after_board = board.copy(stack=True)
            after_board.push(played)
            after = engine.analyze(after_board)
            phase, _, _ = classify_phase(
                board, unknown_history=board.root().fen() != chess.STARTING_FEN
            )
            evidence = MoveCoachingEvidence(
                game_id=i,
                ply=len(board.move_stack) + 1,
                player_color="white" if board.turn else "black",
                phase=phase,
                fen_before=board.fen(),
                initial_fen=board.root().fen(),
                history_uci=tuple(m.uci() for m in board.move_stack),
                history_before_start_unknown=board.root().fen() != chess.STARTING_FEN,
                played_move_uci=played.uci(),
                best_move_uci=before.best_move_uci,
                best_line_uci=before.pv_uci[:16],
                played_refutation_uci=after.pv_uci[:16],
                before=EngineScore(
                    cp_white=before.score_cp_white,
                    mate_white=before.mate_white,
                    mate_winner=before.mate_winner,
                ),
                after=EngineScore(
                    cp_white=after.score_cp_white,
                    mate_white=after.mate_white,
                    mate_winner=after.mate_winner,
                ),
                loss_cp=calculate_loss_cp(
                    before.score_cp_white, after.score_cp_white, board.turn
                )
                if before.score_cp_white is not None
                and after.score_cp_white is not None
                else None,
                completion_provenance="pgn_declaration",
                source_hash=fingerprint(
                    [
                        board.root().fen(),
                        [m.uci() for m in board.move_stack],
                        played.uci(),
                        "synthetic completed declaration",
                    ]
                ),
                profile_hash=profile.hash,
                engine_version=engine.engine_name,
                analysis_version=profile.version,
                draw_policy=profile.draw_policy,
                feature_version=1,
            )
            rows.append(
                {
                    "case_id": f"case_{i:03}",
                    "category": category,
                    "evidence": evidence.model_dump(mode="json"),
                    "engine_config": profile.config,
                    "expected_behavior": {
                        "must_not_invent_moves": True,
                        "must_not_change_facts": True,
                        "expected_status": None,
                    },
                    "review": {
                        "human_theme": None,
                        "reviewer": None,
                        "notes": "Synthetic development evidence. Human review pending; some moves may be sound rather than mistakes.",
                    },
                }
            )
    Path("evaluation/datasets/move_explanations_v1.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    )
    print(f"Saved {len(rows)} fixed evidence snapshots")


if __name__ == "__main__":
    main()
