# Phase 21 · M5 Air benchmark setup

## Scope

This record covers stages 21.0–21.3 on 10 November 2026. The two Stockfish
runs exercised the harness and the third exercised SIGINT recovery. The
subsecond runs do not establish sustained throughput, thermal behavior,
engine quality, or a production configuration.

## 21.0 · Workspace and environment

| Item | Recorded value |
| --- | --- |
| Branch | `perf/m5-air-benchmark` |
| Starting revision | `8a30a0a95ae93ca0f577bd8800785ca666338ce1` |
| Hardware | MacBook Air `Mac17,3`, Apple M5, 10 CPU cores, 16 GiB unified memory |
| System | arm64, macOS 27.0.1 build 26A434 |
| Python | 3.14.6 with python-chess 1.11.2 |
| Engine | Stockfish 19 at `/opt/homebrew/bin/stockfish` |
| Ollama | 0.40.15 |
| Installed model | `qwen3.5:4b-q4_K_M`, Q4_K_M, local ID `d8b0f5e9760c` |

The starting checkout passed Ruff, mypy, pytest, Svelte check and build.
After implementation, Ruff and mypy passed, pytest reported 710 passes and
one skip, and all three opt-in Stockfish tests passed. The opt-in tests exercise
White and Black score orientation, mate, legality, MultiPV and process cleanup.
Run metadata records HEAD, the tracked
diff hash, hashes of the benchmark Python files, and the executable checksum.
The baseline metadata also records the hardware, model details and local
Ollama residency. No model was resident at baseline.

## 21.1 · Frozen dataset

The original local database contained 646 legacy Chess.com rows without
stored source completion evidence. It was queried read-only. The app importer
refreshed the June–October 2026 monthly archives into
`data/benchmarks/source.db`. The sampler revalidated completion evidence,
PGN results and legal play for 609 eligible games in that isolated database.

Seed 42 selects up to 100 games, targeting 20 short, 40 typical, 20 long and
20 endgame-rich games. Endgame-rich takes priority when at least 12 pre-move
positions are labeled endgame by the application's material heuristic. The
remaining buckets use the number of played full moves rounded up from plies
(≤20, 21–50, >50). When a stratum runs short, a seeded draw from the remaining
games fills the sample. The realized sample contained 30 short, 43 typical, six
long and 21 endgame-rich games. It included 59 games played as White and 41
as Black, with 86 rapid, 11 blitz and three daily games. The rapid-heavy
sample and limited long-game stratum reflect the available corpus and
selection policy.

Games are split before positions are selected, with 20% of the game quota
allocated proportionally across the strata. Positions are sampled within phase
and partition, using exact six-field FEN uniqueness across both partitions.
The engine receives the original move prefix, including the starting position
and halfmove clock. The history checksum distinguishes SetUp/FEN starts with
unknown prior history. The draw policy uses automatic fivefold and 75-move
draws and does not assume claimable draws were claimed. Candidate positions
precede played moves, so terminal positions are excluded.

| Partition | Source games | Opening | Middlegame | Endgame | Positions |
| --- | ---: | ---: | ---: | ---: | ---: |
| Calibration | 80 | 48 | 80 | 64 | 192 |
| Holdout | 20 | 12 | 20 | 16 | 48 |
| Total | 100 | 60 | 100 | 80 | 240 |

There are 132 White-to-move and 108 Black-to-move positions. The sampled
positions came from 61 calibration games and 14 holdout games. The smoke
tests used the first 10 calibration positions, which are openings. The
holdout was validated for legality and partition membership and was kept out
of engine runs. Each run validates the frozen file hashes and reconstructed
positions. A repeat build from the isolated source produced byte-identical
game, position and manifest files.

- Dataset version `m5-benchmark-v1`
- Positions SHA-256 `eddc39b847280aba592b43a5438a4a36d3ee9ddf8e64d275b653f0b3240e72ce`
- Games SHA-256 `a5e48afe9e33c2c48a903bc7e5ac2000c0a6cc70999dd87a9945b6427857e52f`

## 21.2 · Harness and smoke evidence

A run launches one Stockfish process and uses a fresh UCI game identity for
every search, causing `ucinewgame` and a ready handshake before the position
is sent. This resets cross-position engine state. Stockfish receives an
explicit node limit, Threads and Hash, and MultiPV 1. The fixed position order
and all settings are recorded. The harness uses the final reported node
count and final UCI best move. It pairs the move with the latest unbounded
score and PV reported for that move, validates the full PV, and records the
depth of that evidence separately from the node count. Centipawn and mate
scores are separate and White-oriented.

Search wall time uses a monotonic clock and includes the UCI reset, dispatch
and response collection. Batch time additionally includes process startup,
evidence validation, result writes and shutdown. Dataset loading and health
probes run outside the measured batch. Results flush after each attempt.
In an orderly interruption the current attempt is marked `INTERRUPTED` and
the remaining planned rows are marked `SKIPPED`.

| Smoke run | Successes | Startup (s) | Search wall (s) | Batch (s) |
| --- | ---: | ---: | ---: | ---: |
| `final-smoke-1` | 10/10 | 0.189 | 0.321 | 0.540 |
| `final-smoke-2` | 10/10 | 0.147 | 0.326 | 0.496 |

Both runs used two threads, 512 MiB hash, 25,000 nodes and one repetition. Both
returned legal best moves and PVs with a valid score and positive node count.
The SIGINT test used one million nodes to allow interruption during a search.
It retained one successful row, wrote one interrupted row and eight skipped
rows, and exited with status 130. The Stockfish process returned 0 and its
recorded PID was absent after cleanup.

## 21.3 · Health baseline and stop rules

Activity Monitor showed green memory pressure. The command-line samples showed
memory pressure level 1 and 2,015.44 MiB of swap in use before and after both
smoke runs. The baseline had 299 GiB free disk space and a one-minute load
average of 2.56. macOS reported battery power for the recorded runs. Physical
setup and ambient conditions were unverified, and the smoke measurements
are limited to functional verification. Use AC power, a hard unobstructed
surface, and a quiet system for sustained comparisons.

| State | Response |
| --- | --- |
| Green pressure, stable swap and responsive system | Continue sampling. |
| Sustained yellow pressure, growing swap, sluggish response, or more than 20% sustained throughput decline | Pause and investigate. A roughly 1 GiB swap increase is an investigation trigger. |
| Sustained red pressure, fast swap growth with freezes, repeated engine crashes, or serious unresponsiveness | Interrupt the run and verify engine exit. |

Inspect Activity Monitor before and after smoke tests, every one to two
minutes during short engine tests, every minute during sustained runs,
before/during/after inference, and every 30–60 seconds during concurrent
workloads. Use Memory Pressure as the main signal and swap growth as context.
RSS only describes part of a unified-memory workload. On interruption, press
Ctrl+C once, check the recorded exit status and engine PID, and use
`ollama ps` followed by `ollama stop MODEL_TAG` only if a benchmark-loaded
model needs to be unloaded.

The dataset is ordered by phase. Compare identical repeated passes when
checking for sustained degradation, since the beginning and end of one pass
contain different positions.

## Independent review

The read-only reviewer passed stages 21.0–21.3 and independently checked the
frozen hashes, the split, the legal PVs and the recorded smoke and interruption
results. Follow-up changes distinguish output-write failures from engine
startup failures and allow an in-progress shutdown to finish after an
interrupt. Focused tests cover startup and output failures. The final runs
above repeat the real search and active-search interruption checks. The
follow-up review passed and used a controlled mock to verify cancellation
during engine shutdown.

## Reproduction

Keep the dataset, disposable archive database and results below the ignored
`data/benchmarks/` directory. The existing frozen dataset and raw runs are
under `datasets/m5-v1/` and `results/` respectively. Reuse the frozen inputs
for future comparisons. Choose new output directories when reproducing a run.

```sh
uv run python -m benchmarks.prepare_dataset \
  --source data/benchmarks/source.db --player-id 1 --seed 42 \
  --output data/benchmarks/datasets/m5-v1-check
shasum -a 256 data/benchmarks/datasets/m5-v1-check/{games,positions}.jsonl

uv run python -m benchmarks.health --label pre-smoke --environment \
  --output data/benchmarks/results/reproduction-baseline/run_metadata.json
uv run python -m benchmarks.benchmark_stockfish \
  --dataset data/benchmarks/datasets/m5-v1 \
  --output data/benchmarks/results/reproduction-smoke \
  --threads 2 --hash-mb 512 --nodes 25000 --limit 10 --repetitions 1
```

If the isolated source database needs rebuilding, set
`CHESS_COACH_DATABASE_PATH` to a fresh database below `data/benchmarks/`,
apply `uv run alembic upgrade head`, and use the existing `chess-coach sync`
command with the tracked Chess.com username and one `--month YYYY/MM` per
archived month. Upstream archives can change, so compare the frozen hashes
before treating regenerated inputs as equivalent. For interrupt verification,
repeat the smoke command with a new output directory and `--nodes 1000000`.
Send Ctrl+C after the first result appears, then inspect the JSONL statuses
and the engine exit status.
