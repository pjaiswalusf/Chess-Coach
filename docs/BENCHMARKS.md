# M5 Air benchmarks

Measured on 10 November 2026 on the [recorded M5 Air](benchmarks/environment.md).
The historical engine dataset is kept locally. Its [manifest methodology and
checksums](benchmarks/m5-air.md#211--frozen-dataset) identify the fixed games,
position history, sampling seed and partitions. The engine sweep uses all
192 calibration positions in the same order for each of three repetitions.
The 48 held-out positions are excluded. Each search uses Stockfish 19 with
250,000 nodes, 512 MiB hash, MultiPV 1 and a new UCI game identity. The benchmark
does not use the application position cache.

The measured run files are under `data/benchmarks/phase23/`. Stockfish emits
`run_metadata.json` and per-attempt `positions.jsonl`. The comparison uses
`model-alone.json`, `model-concurrent.json` and `combined-wall-seconds.txt`.
The cache trials write `cache-cold.db.json` and `cache-warm.db.json`.

## Stockfish sweep

| Threads | Accepted / attempted | Rejected | Batch seconds | Accepted positions/s | Search seconds by repetition |
| --- | --- | --- | --- | --- | --- |
| 2 | 574 / 576 | 2 | 115.20 | 4.98 | 36.74, 38.70, 39.26 |
| 4 | 575 / 576 | 1 | 67.33 | 8.54 | 20.56, 22.65, 23.65 |
| 6 | 575 / 576 | 1 | 58.39 | 9.85 | 18.22, 18.73, 21.01 |

Batch time includes engine startup, result validation, writes and shutdown.
Throughput divides accepted searches by batch seconds. The harness rejected
four searches because there was no unbounded score and PV matching the final
UCI best move. The rejected positions were `pos_0020` and `pos_0138` at two
threads and `pos_0144` at four and six threads. A failed run keeps its
successful rows and returns a failure status.

The last repetition took approximately 7–15% longer than the first. Before
and after each batch, macOS reported pressure level 1 and 2,612.81 MiB swap
in use. The trials ran in fixed thread order on battery power. These are
short sustained batches on one machine. Temperature, run-order effects and
longer steady-state behavior remain unmeasured, so the results do not
establish an optimal setting.

```sh
for threads in 2 4 6; do
  uv run --locked python -m benchmarks.benchmark_stockfish \
    --dataset data/benchmarks/datasets/m5-v1 \
    --output "data/benchmarks/reproduction/stockfish-t$threads" \
    --threads "$threads" --hash-mb 512 --nodes 250000 --repetitions 3
done
```

The position sweep requires the matching frozen dataset, which is outside a
fresh public checkout. The seven-fixture cache experiment below is self-contained.
Use a new output directory on every run. Keep raw games, positions and host
metadata under the ignored `data/benchmarks/` directory.

## Engine and model resource contention

The engine workload was one pass over the same 192 calibration positions at
four threads. The model workload was the same 12 move cases in each trial,
with `keep_alive=0` and the [recorded generation settings](EVALUATION.md).
The concurrent trial started both processes together.

| Trial | Engine accepted / attempted | Engine batch | Engine accepted/s | Model calls | Model p50 / p95 |
| --- | --- | --- | --- | --- | --- |
| Engine alone | 192 / 192 | 25.00 s | 7.68 | — | — |
| Model alone | — | — | — | 12 | 3.15 s / 4.10 s |
| Concurrent | 191 / 192 | 48.11 s | 3.97 | 12 | 5.77 s / 7.24 s |

Concurrent launch-to-exit wall time was 72 seconds at one-second resolution.
The sum of the isolated engine batch and individual model call durations was
63.51 seconds, excluding process startup for the model runner and health
sampling. Concurrent execution reduced engine throughput and increased model
latency in this trial. The measured engine failure was a missing compatible
unbounded score and PV. Both model runs accepted one of 12 first responses.

The host reported pressure level 1 before and after each trial. Swap was
unchanged at 2,612.81 MiB across the isolated model run and at 2,604.81 MiB
across the concurrent run. These are endpoint samples. Peak pressure and
temperature during overlap are unmeasured.

Repeat the thread-sweep engine command with `--threads 4 --repetitions 1` and
the [12-case model command](EVALUATION.md#reproduce) individually and then start
both commands at the same time. Use separate output paths and preserve the same
engine binary, model digest, position order and settings.

## Cold and warm application cache

Both trials ran the production analysis worker on the same seven synthetic
PGN fixtures, with Stockfish 19, four threads, 512 MiB hash and 10,000 nodes.
Both databases began with the same parsed games and no completed game analyses.
Only the second database received the first database's position-cache rows.

| Trial | Completed games | Engine calls | Cache hits / lookups | Worker wall time |
| --- | --- | --- | --- | --- |
| Cold start | 7 / 7 | 17 | 15 / 34 | 0.485 s |
| Warm start | 7 / 7 | 0 | 34 / 34 | 0.244 s |

On cold start, positions shared within the batch account for 15 hits, and
two of the 19 misses were terminal positions that required no search. The
warm trial processed all seven games again. A later run against either already
completed database skips seven compatible games, which is a separate
behavior. These subsecond runs demonstrate cache reuse on a fixed workload.
They do not estimate a typical speedup on a personal library.

```sh
mkdir -p data/benchmarks/cache-reproduction
export CHESS_COACH_STOCKFISH_THREADS=4
export CHESS_COACH_STOCKFISH_HASH_MB=512
export CHESS_COACH_STOCKFISH_NODES=10000
uv run --locked python scripts/benchmark_phase10.py --fixtures --games 7 \
  --database data/benchmarks/cache-reproduction/cold.db
uv run --locked python scripts/benchmark_phase10.py --fixtures --games 7 \
  --database data/benchmarks/cache-reproduction/warm.db \
  --cache-from data/benchmarks/cache-reproduction/cold.db
```
