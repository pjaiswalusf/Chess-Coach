"""Run independent node-limited Stockfish searches on a frozen dataset."""

import argparse
import asyncio
import json
import shutil
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import TextIO

import chess
import chess.engine

from benchmarks.health import revision, snapshot, utc_now
from benchmarks.prepare_dataset import (
    PARTITIONS,
    Position,
    load_dataset,
    private_path,
    sha256,
)
from chess_coach.domain.analysis import validate_result
from chess_coach.domain.engine_types import EngineResult
from chess_coach.domain.score_utils import normalize_score

CACHE_POLICY = "fresh UCI game per search; ucinewgame + ready handshake; no app cache"
TIMEOUT_SECONDS = 60


async def search(
    engine: chess.engine.UciProtocol,
    board: chess.Board,
    nodes: int,
) -> tuple[EngineResult, int, float]:
    started = perf_counter()
    exact: dict[chess.Move, chess.engine.InfoDict] = {}
    actual_nodes = None
    async with asyncio.timeout(TIMEOUT_SECONDS):
        with await engine.analysis(
            board,
            chess.engine.Limit(nodes=nodes),
            game=object(),
            multipv=1,
        ) as analysis:
            async for update in analysis:
                if "nodes" in update:
                    actual_nodes = update["nodes"]
                pv = update.get("pv")
                if (
                    pv
                    and "score" in update
                    and not update.get("lowerbound")
                    and not update.get("upperbound")
                ):
                    exact[pv[0]] = update
            best = await analysis.wait()
    elapsed = perf_counter() - started
    if best.move is None or best.move not in exact:
        raise ValueError("No unbounded score and PV matching final UCI bestmove")
    if type(actual_nodes) is not int or actual_nodes <= 0:
        raise ValueError("Stockfish did not report positive node telemetry")
    evidence = exact[best.move]
    score = evidence["score"]
    cp, mate = normalize_score(score)
    result = EngineResult(
        board.fen(),
        engine.id["name"],
        cp,
        mate,
        score.white() > chess.engine.Cp(0) if mate is not None else None,
        best.move.uci(),
        tuple(move.uci() for move in evidence["pv"]),
        evidence.get("depth"),
        actual_nodes,
    )
    validate_result(board, result, engine.id["name"])
    return result, actual_nodes, elapsed


def write_record(output: TextIO, record: dict) -> None:
    output.write(json.dumps(record, sort_keys=True) + "\n")
    output.flush()


async def stop_engine(
    transport: asyncio.SubprocessTransport,
    engine: chess.engine.UciProtocol,
    metadata: dict,
) -> None:
    try:
        if not engine.returncode.done():
            await asyncio.wait_for(engine.quit(), TIMEOUT_SECONDS)
    except (chess.engine.EngineError, OSError) as exc:
        metadata["cleanup_error_type"] = type(exc).__name__
    finally:
        transport.close()
    try:
        metadata["engine_returncode"] = await asyncio.wait_for(
            asyncio.shield(engine.returncode),
            TIMEOUT_SECONDS,
        )
    except TimeoutError:
        metadata["cleanup_error_type"] = "EngineExitUnconfirmed"
    if (
        metadata.get("cleanup_error_type") or metadata.get("engine_returncode") != 0
    ) and metadata["status"] == "DONE":
        metadata["status"] = "FAILED"


async def measure(
    output: TextIO,
    metadata: dict,
    entries: list[tuple[Position, chess.Board]],
) -> None:
    plan = [
        (repetition, position, board)
        for repetition in range(1, metadata["repetitions"] + 1)
        for position, board in entries
    ]
    counts: Counter[str] = Counter()
    cursor = 0
    active_started = None
    search_seconds = 0.0
    transport = engine = None
    batch_started = perf_counter()

    def record(status: str, **fields: object) -> None:
        nonlocal cursor
        repetition, position, _ = plan[cursor]
        row = {
            "run_id": metadata["run_id"],
            "position_id": position.position_id,
            "repetition": repetition,
            "status": status,
            "threads": metadata["threads"],
            "hash_mb": metadata["hash_mb"],
            "node_budget": metadata["node_budget"],
            "multipv": metadata["multipv"],
            "wall_time_seconds": None,
            "actual_nodes": None,
            "best_move_uci": None,
            "score_cp_white": None,
            "mate_white": None,
            "error_type": None,
            **fields,
        }
        try:
            write_record(output, row)
        except OSError:
            metadata["output_may_be_incomplete"] = True
            raise
        cursor += 1
        counts[status] += 1

    try:
        startup_started = perf_counter()
        async with asyncio.timeout(TIMEOUT_SECONDS):
            transport, engine = await chess.engine.popen_uci(
                metadata["stockfish_executable"],
                setpgrp=True,
            )
            metadata["engine_pid"] = transport.get_pid()
            metadata["engine_id"] = dict(engine.id)
            if not engine.id.get("name"):
                raise chess.engine.EngineError("Missing UCI engine name")
            await engine.configure(
                {"Threads": metadata["threads"], "Hash": metadata["hash_mb"]}
            )
            await engine.ping()
        metadata["engine_startup_seconds"] = perf_counter() - startup_started

        while cursor < len(plan):
            _, _, board = plan[cursor]
            active_started = perf_counter()
            fatal = False
            try:
                result, nodes, elapsed = await search(
                    engine, board, metadata["node_budget"]
                )
            except (chess.engine.EngineError, OSError, ValueError) as exc:
                elapsed = perf_counter() - active_started
                record(
                    "FAILED",
                    wall_time_seconds=elapsed,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                fatal = isinstance(exc, (chess.engine.EngineTerminatedError, OSError))
            else:
                record(
                    "SUCCEEDED",
                    wall_time_seconds=elapsed,
                    actual_nodes=nodes,
                    best_move_uci=result.best_move_uci,
                    pv_uci=result.pv_uci,
                    score_cp_white=result.score_cp_white,
                    mate_white=result.mate_white,
                    evidence_depth=result.depth,
                )
            search_seconds += elapsed
            active_started = None
            if fatal:
                break
        metadata["status"] = "FAILED" if counts["FAILED"] else "DONE"
    except asyncio.CancelledError:
        metadata["status"] = "INTERRUPTED"
        if active_started is not None:
            elapsed = perf_counter() - active_started
            search_seconds += elapsed
            record(
                "INTERRUPTED", wall_time_seconds=elapsed, error_type="KeyboardInterrupt"
            )
        raise
    except (chess.engine.EngineError, OSError, ValueError) as exc:
        metadata.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
        # A broken output can leave a valid prefix. Avoid retrying writes to it.
        if metadata.get("output_may_be_incomplete"):
            raise
    finally:
        try:
            if engine is not None and transport is not None:
                cleanup = asyncio.create_task(stop_engine(transport, engine, metadata))
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    metadata["status"] = "INTERRUPTED"
                    await cleanup
                    raise
        finally:
            try:
                if not metadata.get("output_may_be_incomplete"):
                    while cursor < len(plan):
                        record("SKIPPED", error_type=metadata["status"])
            finally:
                metadata["record_counts"] = dict(counts)
                metadata["attempted"] = sum(
                    counts[s] for s in ("SUCCEEDED", "FAILED", "INTERRUPTED")
                )
                metadata["search_wall_seconds"] = search_seconds
                metadata["batch_total_seconds"] = perf_counter() - batch_started


def save_metadata(path: Path, metadata: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(metadata, indent=2) + "\n")
    temporary.replace(path)


def run(args: argparse.Namespace) -> dict:
    manifest, entries = load_dataset(private_path(args.dataset))
    entries = [
        (position, board)
        for position, board in entries
        if position.partition == args.partition
    ]
    if args.limit is not None:
        entries = entries[: args.limit]
    if not entries:
        raise ValueError(f"No positions in partition {args.partition}")
    executable = shutil.which(args.engine)
    if executable is None:
        raise ValueError("Stockfish executable not found")
    path = private_path(args.output)
    path.mkdir(parents=True, exist_ok=False)
    metadata_path = path / "run_metadata.json"
    metadata = {
        **revision(),
        "run_id": path.name,
        "status": "RUNNING",
        "started_at_utc": utc_now(),
        "dataset_version": manifest["dataset_version"],
        "positions_sha256": manifest["positions_sha256"],
        "games_sha256": manifest["games_sha256"],
        "draw_policy": manifest["draw_policy"],
        "partition": args.partition,
        "position_order": [position.position_id for position, _ in entries],
        "cache_reset_policy": CACHE_POLICY,
        "stockfish_executable": executable,
        "stockfish_executable_sha256": sha256(Path(executable).read_bytes()),
        "threads": args.threads,
        "hash_mb": args.hash_mb,
        "node_budget": args.nodes,
        "multipv": 1,
        "repetitions": args.repetitions,
        "planned": len(entries) * args.repetitions,
        "engine_startup_seconds": None,
        "health_before": snapshot(),
    }
    save_metadata(metadata_path, metadata)
    try:
        with (path / "positions.jsonl").open("x") as output:
            asyncio.run(measure(output, metadata, entries))
    except KeyboardInterrupt:
        metadata["status"] = "INTERRUPTED"
    except OSError as exc:
        metadata.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
    finally:
        metadata["finished_at_utc"] = utc_now()
        try:
            metadata["health_after"] = snapshot()
            save_metadata(metadata_path, metadata)
        except KeyboardInterrupt:
            metadata["status"] = "INTERRUPTED"
            save_metadata(metadata_path, metadata)
    return metadata


def positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine", default="stockfish")
    parser.add_argument("--threads", type=positive, required=True)
    parser.add_argument("--nodes", type=positive, required=True)
    parser.add_argument("--hash-mb", type=positive, default=512)
    parser.add_argument("--partition", choices=PARTITIONS, default="calibration")
    parser.add_argument("--limit", type=positive)
    parser.add_argument("--repetitions", type=positive, default=1)
    args = parser.parse_args()
    try:
        result = run(args)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Benchmark could not run: {exc}\n")
    print(f"{result['run_id']}: {result['status']} {result.get('record_counts', {})}")
    if result["status"] != "DONE":
        parser.exit(130 if result["status"] == "INTERRUPTED" else 1)


if __name__ == "__main__":
    main()
