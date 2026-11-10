"""Regression checks for frozen inputs and independent UCI measurements."""

import asyncio
import json
import sqlite3
from contextlib import closing
from io import StringIO
from pathlib import Path

import chess
import chess.engine
import pytest

from benchmarks.benchmark_stockfish import measure, search
from benchmarks.prepare_dataset import Position, load_dataset, prepare

PGNS = Path(__file__).resolve().parents[1] / "fixtures" / "pgn"


def test_frozen_dataset_preserves_history_and_splits_by_completed_source_game(tmp_path):
    source = tmp_path / "source.db"
    with closing(sqlite3.connect(source)) as db, db:
        db.executescript(
            """
            CREATE TABLE tracked_players (id INTEGER, username TEXT);
            INSERT INTO tracked_players VALUES (1, 'Pratik');
            CREATE TABLE games (
                id INTEGER, tracked_player_id INTEGER, raw_pgn TEXT, platform TEXT,
                white_username TEXT, black_username TEXT, source_evidence TEXT, time_class TEXT
            );
            """
        )
        for game_id, name, platform in (
            (1, "white_win", "pgn"),
            (2, "black_win", "pgn"),
            (3, "custom", "pgn"),
            (4, "white_win", "chess.com"),
        ):
            db.execute(
                "INSERT INTO games VALUES (?, 1, ?, ?, 'Pratik', 'Opponent', NULL, 'rapid')",
                (game_id, (PGNS / f"{name}.pgn").read_text(), platform),
            )

    original = source.read_bytes()
    dataset = tmp_path / "dataset"
    manifest = prepare(source, 1, dataset, 42)
    assert source.read_bytes() == original
    assert manifest == prepare(source, 1, tmp_path / "repeat", 42)
    assert manifest["excluded_games_by_reason"] == {"SOURCE_EVIDENCE_MISSING": 1}
    assert manifest["games_by_partition"] == {"calibration": 2, "holdout": 1}

    _, entries = load_dataset(dataset)
    groups = {
        partition: {
            position.game_id
            for position, _ in entries
            if position.partition == partition
        }
        for partition in ("calibration", "holdout")
    }
    assert groups["calibration"] and groups["holdout"]
    assert groups["calibration"].isdisjoint(groups["holdout"])
    assert len({position.fen for position, _ in entries}) == len(entries)
    assert all(len(board.move_stack) == position.ply for position, board in entries)
    assert any(
        position.game_id == 3 and board.root().halfmove_clock == 17
        for position, board in entries
    )

    positions = dataset / "positions.jsonl"
    positions.write_bytes(positions.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_dataset(dataset)


class UciStream:
    def __init__(self, updates, best):
        self.updates = updates
        self.best = best

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    async def __aiter__(self):
        for update in self.updates:
            yield update

    async def wait(self):
        return chess.engine.BestMove(self.best, None)


class ScriptedUci:
    def __init__(self, updates, best):
        self.id = {"name": "Fake Stockfish"}
        self.stream = UciStream(updates, best)
        self.calls = []

    async def analysis(self, board, limit, *, game, multipv):
        self.calls.append((board, limit, game, multipv))
        return self.stream


def test_search_records_final_nodes_with_exact_white_score_and_fresh_game():
    board = chess.Board()
    board.push_uci("e2e4")
    move = chess.Move.from_uci("e7e5")
    engine = ScriptedUci(
        [
            {
                "depth": 6,
                "nodes": 20,
                "pv": [move],
                "score": chess.engine.PovScore(chess.engine.Cp(35), chess.BLACK),
            },
            {
                "depth": 7,
                "nodes": 51,
                "pv": [move],
                "score": chess.engine.PovScore(chess.engine.Cp(12), chess.BLACK),
                "upperbound": True,
            },
        ],
        move,
    )

    result, actual_nodes, elapsed = asyncio.run(search(engine, board, 50))
    asyncio.run(search(engine, board, 50))
    assert engine.calls[0][0].move_stack == board.move_stack
    assert engine.calls[0][1] == chess.engine.Limit(nodes=50)
    assert engine.calls[0][2] is not engine.calls[1][2]
    assert engine.calls[0][3] == 1
    assert result.best_move_uci == "e7e5"
    assert result.score_cp_white == -35 and result.mate_white is None
    assert result.depth == 6 and result.nodes == actual_nodes == 51
    assert elapsed >= 0


def test_search_rejects_missing_exact_score_for_the_final_move():
    board = chess.Board()
    engine = ScriptedUci(
        [
            {
                "depth": 6,
                "nodes": 20,
                "pv": [chess.Move.from_uci("e2e4")],
                "score": chess.engine.PovScore(chess.engine.Mate(3), chess.WHITE),
            },
        ],
        chess.Move.from_uci("d2d4"),
    )
    with pytest.raises(ValueError, match="matching final UCI bestmove"):
        asyncio.run(search(engine, board, 50))


@pytest.mark.parametrize("writer_fails", [False, True])
def test_startup_and_output_failures_are_distinguished(monkeypatch, writer_fails):
    async def missing_engine(*args, **kwargs):
        raise FileNotFoundError("missing engine")

    class FailingOutput(StringIO):
        def write(self, value):
            raise OSError("output is full")

    monkeypatch.setattr(chess.engine, "popen_uci", missing_engine)
    board = chess.Board()
    position = Position("p1", 1, 0, board.fen(), "opening", "white", "", "calibration")
    metadata = {
        "run_id": "test",
        "stockfish_executable": "missing",
        "repetitions": 1,
        "threads": 2,
        "hash_mb": 512,
        "node_budget": 25000,
        "multipv": 1,
    }
    output = FailingOutput() if writer_fails else StringIO()
    measurement = measure(output, metadata, [(position, board)])
    if writer_fails:
        with pytest.raises(OSError, match="output is full"):
            asyncio.run(measurement)
        assert metadata["output_may_be_incomplete"]
    else:
        asyncio.run(measurement)
        assert json.loads(output.getvalue())["status"] == "SKIPPED"
        assert "output_may_be_incomplete" not in metadata
    assert metadata["status"] == "FAILED"
    assert metadata["error_type"] == "FileNotFoundError"
