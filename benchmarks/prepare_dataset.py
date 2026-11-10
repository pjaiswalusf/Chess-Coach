"""Freeze a history-preserving sample from one player's local game archive."""

import argparse
import hashlib
import json
import random
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TypedDict

import chess

from chess_coach.analytics.phases import classify_phase
from chess_coach.application.parse_imported_games import ParseInput, _source_result
from chess_coach.domain.analysis import DRAW_POLICY, history_hash
from chess_coach.domain.feature_models import GamePhase
from chess_coach.domain.game_records import PARSER_VERSION, PGNParseError, ReasonCode
from chess_coach.infrastructure.pgn.parser import parse_game

PRIVATE_ROOT = Path(__file__).resolve().parents[1] / "data" / "benchmarks"
VERSION = "m5-benchmark-v1"
GAME_TARGETS = {"short": 20, "typical": 40, "long": 20, "endgame-rich": 20}
POSITION_TARGETS = {"opening": 60, "middlegame": 100, "endgame": 80}
PARTITIONS = ("calibration", "holdout")


@dataclass(frozen=True)
class Position:
    position_id: str
    game_id: int
    ply: int
    fen: str
    phase: str
    side_to_move: str
    history_sha256: str
    partition: str


class SampleGame(TypedDict):
    game_id: int
    raw_pgn: str
    platform: str
    player_color: str
    time_class: str | None
    time_control: str | None
    source_result: str
    start_fen: str
    history_before_start_unknown: bool
    moves: list[str]
    bucket: str
    partition: str


type CandidatePosition = tuple[int, str, str, str]
type CandidateGame = tuple[SampleGame, list[CandidatePosition]]


def private_path(path: Path) -> Path:
    path = path.resolve()
    if PRIVATE_ROOT.resolve() not in path.parents:
        raise ValueError(
            "Choose a path below data/benchmarks/ for private benchmark data"
        )
    return path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jsonl(rows) -> bytes:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode()


def candidates(
    source: Path, player_id: int
) -> tuple[list[CandidateGame], Counter[str]]:
    with closing(
        sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    ) as db:
        rows = db.execute(
            """
            SELECT g.id, g.raw_pgn, p.username, g.platform, g.white_username,
                   g.black_username, g.source_evidence, g.time_class
            FROM games g JOIN tracked_players p ON p.id = g.tracked_player_id
            WHERE p.id = ? ORDER BY g.id
            """,
            (player_id,),
        ).fetchall()
    rejected: Counter[str] = Counter()
    games: list[CandidateGame] = []
    for game_id, pgn, username, platform, white, black, evidence, time_class in rows:
        record = ParseInput(
            game_id,
            pgn,
            username,
            platform,
            white,
            black,
            json.loads(evidence) if evidence is not None else None,
        )
        try:
            expected, final_fen = _source_result(record)
            parsed = parse_game(pgn, username, source_final_fen=final_fen)
            if expected is not None and parsed.source_result != expected:
                raise PGNParseError(ReasonCode.RESULT_MISMATCH)
            if (parsed.white_username.casefold(), parsed.black_username.casefold()) != (
                white.strip().casefold(),
                black.strip().casefold(),
            ):
                raise PGNParseError(ReasonCode.SOURCE_METADATA_MISMATCH)
        except PGNParseError as exc:
            rejected[exc.reason_code] += 1
            continue

        board = chess.Board(parsed.initial_fen)
        phase = None
        positions = []
        for ply, move in enumerate(parsed.moves):
            phase, _, _ = classify_phase(
                board,
                phase,
                unknown_history=parsed.history_before_start_unknown,
            )
            if phase != GamePhase.UNCLASSIFIED:
                positions.append(
                    (ply, board.fen(), phase.value, move.mover_color.value)
                )
            board.push_uci(move.uci)
        if not positions:
            rejected["NO_CLASSIFIED_POSITIONS"] += 1
            continue
        full_moves = (parsed.total_plies + 1) // 2
        if sum(phase == "endgame" for _, _, phase, _ in positions) >= 12:
            bucket = "endgame-rich"
        elif full_moves <= 20:
            bucket = "short"
        elif full_moves <= 50:
            bucket = "typical"
        else:
            bucket = "long"
        games.append(
            (
                {
                    "game_id": game_id,
                    "raw_pgn": pgn,
                    "platform": platform,
                    "player_color": parsed.player_color.value,
                    "time_class": time_class,
                    "time_control": parsed.time_control.raw,
                    "source_result": parsed.source_result,
                    "start_fen": parsed.initial_fen,
                    "history_before_start_unknown": parsed.history_before_start_unknown,
                    "moves": [move.uci for move in parsed.moves],
                    "bucket": bucket,
                    "partition": "",
                },
                positions,
            )
        )
    return games, rejected


def prepare(source: Path, player_id: int, output: Path, seed: int) -> dict:
    games, rejected = candidates(source, player_id)
    if len(games) < 2:
        raise ValueError(
            f"Need at least two eligible completed games. Exclusions: {dict(rejected)}"
        )
    rng = random.Random(seed)
    groups: dict[str, list[CandidateGame]] = {bucket: [] for bucket in GAME_TARGETS}
    rng.shuffle(games)
    for item in games:
        groups[item[0]["bucket"]].append(item)
    selected = []
    reserve = []
    for bucket, target in GAME_TARGETS.items():
        selected.extend(groups[bucket][:target])
        reserve.extend(groups[bucket][target:])
    rng.shuffle(reserve)
    selected.extend(reserve[: sum(GAME_TARGETS.values()) - len(selected)])

    # Proportional holdout quotas per selected game stratum, with seeded order
    # inside each stratum. Allocate rounding leftovers to largest remainders.
    bucket_counts = Counter(game["bucket"] for game, _ in selected)
    quotas = {bucket: count // 5 for bucket, count in bucket_counts.items()}
    holdout_count = max(1, round(len(selected) / 5))
    for bucket in sorted(bucket_counts, key=lambda b: -(bucket_counts[b] % 5))[
        : holdout_count - sum(quotas.values())
    ]:
        quotas[bucket] += 1
    pool: dict[tuple[str, str], list[tuple[SampleGame, int, str, str]]] = {
        (partition, phase): [] for partition in PARTITIONS for phase in POSITION_TARGETS
    }
    for game, positions in selected:
        bucket = game["bucket"]
        partition = "holdout" if quotas[bucket] else "calibration"
        quotas[bucket] -= int(partition == "holdout")
        game["partition"] = partition
        for ply, fen, phase, side in positions:
            pool[partition, phase].append((game, ply, fen, side))

    used_fens = set()
    chosen: list[Position] = []
    for (partition, phase), group in pool.items():
        rng.shuffle(group)
        target = POSITION_TARGETS[phase] // 5
        if partition == "calibration":
            target *= 4
        count = 0
        for game, ply, fen, side in group:
            if fen in used_fens:
                continue
            used_fens.add(fen)
            board = chess.Board(game["start_fen"])
            for uci in game["moves"][:ply]:
                board.push_uci(uci)
            chosen.append(
                Position(
                    f"pos_{len(chosen) + 1:04d}",
                    game["game_id"],
                    ply,
                    fen,
                    phase,
                    side,
                    history_hash(board, game["history_before_start_unknown"]),
                    partition,
                )
            )
            count += 1
            if count == target:
                break

    games_data = jsonl(game for game, _ in selected)
    positions_data = jsonl(asdict(position) for position in chosen)
    manifest = {
        "dataset_version": VERSION,
        "selection_seed": seed,
        "selection_strategy": "length/endgame strata, game-level split, phase quotas, unique FEN",
        "source_player_id": player_id,
        "eligible_games": len(games),
        "excluded_games_by_reason": dict(rejected),
        "games_selected": len(selected),
        "games_by_bucket": dict(bucket_counts),
        "games_by_tracked_color": dict(
            Counter(game["player_color"] for game, _ in selected)
        ),
        "games_by_time_class": dict(
            Counter(game["time_class"] or "unknown" for game, _ in selected)
        ),
        "games_by_partition": dict(Counter(game["partition"] for game, _ in selected)),
        "positions_by_partition_and_phase": {
            partition: dict(
                Counter(p.phase for p in chosen if p.partition == partition)
            )
            for partition in PARTITIONS
        },
        "positions_by_side_to_move": dict(Counter(p.side_to_move for p in chosen)),
        "games_sha256": sha256(games_data),
        "positions_sha256": sha256(positions_data),
        "draw_policy": DRAW_POLICY,
        "parser_version": PARSER_VERSION,
        "chess_library_version": chess.__version__,
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "games.jsonl").write_bytes(games_data)
    (output / "positions.jsonl").write_bytes(positions_data)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_dataset(dataset: Path):
    manifest = json.loads((dataset / "manifest.json").read_bytes())
    if manifest["dataset_version"] != VERSION or manifest["draw_policy"] != DRAW_POLICY:
        raise ValueError("Unsupported benchmark dataset or draw policy")
    rows = {}
    for name in ("games", "positions"):
        data = (dataset / f"{name}.jsonl").read_bytes()
        if sha256(data) != manifest[f"{name}_sha256"]:
            raise ValueError(f"Frozen dataset checksum mismatch: {name}.jsonl")
        rows[name] = [json.loads(line) for line in data.splitlines()]
    games = {game["game_id"]: game for game in rows["games"]}
    if len(games) != len(rows["games"]):
        raise ValueError("Duplicate source game ID")
    entries = []
    ids, fens = set(), set()
    for row in rows["positions"]:
        position = Position(**row)
        game = games[position.game_id]
        if (
            position.position_id in ids
            or position.fen in fens
            or position.partition != game["partition"]
            or position.partition not in PARTITIONS
            or position.phase not in POSITION_TARGETS
            or not 0 <= position.ply < len(game["moves"])
        ):
            raise ValueError("Duplicate or inconsistent dataset position")
        board = chess.Board(game["start_fen"])
        if not board.is_valid():
            raise ValueError("Invalid dataset starting position")
        for uci in game["moves"][: position.ply]:
            if board.is_game_over(claim_draw=False):
                raise ValueError("Dataset history continues beyond a terminal board")
            board.push_uci(uci)
        side = "white" if board.turn else "black"
        if (
            not board.is_valid()
            or board.is_game_over(claim_draw=False)
            or board.fen() != position.fen
            or side != position.side_to_move
            or history_hash(board, game["history_before_start_unknown"])
            != position.history_sha256
        ):
            raise ValueError("Invalid or mismatched dataset position history")
        ids.add(position.position_id)
        fens.add(position.fen)
        entries.append((position, board))
    return manifest, entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--player-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        manifest = prepare(
            args.source, args.player_id, private_path(args.output), args.seed
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Dataset preparation failed: {exc}\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
