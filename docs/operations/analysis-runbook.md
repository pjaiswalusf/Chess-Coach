# Local analysis operations

Run from the repository root so all processes resolve the same `.env` and SQLite
path. Back up with SQLite's backup API before migrations; stop API, import, and
worker processes while upgrading. Do not copy a live SQLite file without its WAL.

```sh
uv run alembic upgrade head
uv run chess-coach doctor
uv run chess-coach parse-games --username YOUR_NAME
```

In separate terminals:

```sh
uv run chess-coach serve
uv run chess-coach analysis-worker
cd frontend && pnpm dev
```

Open the local frontend, select an imported player, and choose **Analyze eligible
games**. The API requires a live worker before accepting a request. This prevents
silently queued work with an unknown engine version. An empty or all-compatible
run completes immediately without searches. The worker does a startup engine
handshake even while idle. `analysis-worker --once` processes one pending run and
exits; the ordinary command remains available for subsequent submissions.

Legacy Chess.com rows without source completion evidence remain excluded. To
refresh their source evidence, explicitly rescan with
`uv run chess-coach sync --username YOUR_NAME --force`, then
`uv run chess-coach parse-games --username YOUR_NAME --retry`.
Do not relabel legacy Chess.com records as PGN uploads to bypass this check.

## Persistent state and profiles

- Runs: pending → running → done / completed_with_errors / failed / cancelled.
  Terminal runs are immutable attempts. Retry creates a new snapshot of eligible
  games and skips verified compatible completions.
- Progress is `(completed + failed + skipped) / total`; success excludes failed.
  Excluded, unvalidated inputs are reported separately from the workload.
- One kernel file lock per canonical database path is held for the worker's
  lifetime. Do not delete the lock file: its existence is not ownership.
  A fresh process acquires the lock before recovering running work. Heartbeat
  staleness alone never grants permission to steal a run.
- SIGTERM stops at a position boundary and leaves an interrupted run recoverable.
  Cancellation is persisted and stops at a position boundary, preserving cache
  entries and completed games. The current bounded search may finish first.
- A worker restart with matching settings resumes running attempts. A changed
  engine/profile fails the interrupted attempt explicitly; use the old settings
  to finish it first, or start a new run. No automatic global reanalysis occurs.
- Completed move rows and state commit together. Cache entries commit separately.
  Old profiles remain distinct; no current-profile label is applied to old scores.
- Unknown history before SetUp/FEN remains explicitly unknown. Cache identity
  includes initial FEN, ordered supplied moves, full current FEN/counters, unknown
  history, engine identity, analysis version, configuration, and draw policy.
  Claimable threefold/50-move draws are not automatically scored as drawn;
  automatic fivefold/75-move draws are terminal.
- Scores are White-centric. Loss uses the mover's perspective and is clamped at
  zero. Mate is never converted to CP; winner is retained even for mate distance
  zero. All losses are single-pass estimates; severity/phase labels remain unset.

## Configuration

`CHESS_COACH_STOCKFISH_NODES` defaults to 10000, `THREADS` to 4, `HASH_MB` to 512,
`SEARCH_SECONDS` to 3 and `TIMEOUT_SECONDS` to 10. These names use the
`CHESS_COACH_STOCKFISH_` prefix. `CHESS_COACH_ANALYSIS_MIN_FREE_MB` defaults to 256.
The worker checks free disk before claiming work; a later disk error rolls back
its current transaction and leaves committed work intact. Stop and restart the
worker to apply configuration. A node-budget change produces a new profile.

The adapter owns a bounded search plus protocol watchdog and closes only its
own engine process. A failed search gets one explicit restart/retry. Persistent
engine failure fails the run rather than labelling every remaining game corrupt.
SQLite waits up to five seconds for locks; the worker retries database operations
with at most three failed outer attempts, recovering only unfinished work under
its existing ownership. There is no infinite retry policy.

## Failure response

| Failure | Detection | Recovery |
| --- | --- | --- |
| Engine missing/startup failure | Worker exits; worker status unavailable | Restore executable/configuration, run doctor, restart worker |
| Search timeout/process death | Bounded adapter error; one retry then ENGINE_UNAVAILABLE | Check worker logs; restart and retry eligible games |
| Invalid result or PV | ENGINE_INVALID_RESULT on game; no invalid cache write | Inspect engine/cache provenance; preserve evidence for diagnosis; recompute using a corrected profile or restore a known-good backup |
| Invalid or changed PGN | INVALID_GAME; other games continue | Correct/reimport source, explicitly revalidate, then retry |
| Worker crash | Lost kernel ownership; status unavailable | Restart with original profile; committed games and cached positions survive |
| API crash / browser closes | Disconnected UI | Worker continues independently; restart API/reopen browser |
| SQLite busy | Safe API error or worker OperationalError | Stop competing writers; bounded retry, then restart worker if necessary |
| Database unavailable | DATABASE_UNAVAILABLE with actionable API message | Check path, permissions, disk, migration state; do not delete the database |
| Low disk | DISK_SPACE_LOW before claim | Free space and restart; do not discard completed analyses |
| Duplicate run/worker | ANALYSIS_ALREADY_RUNNING / kernel lock rejection | Inspect active run; use its progress or cancel it |
| Profile changed | ANALYSIS_PROFILE_MISMATCH | Resume with original engine/settings or start a distinct profile |
| Cancellation | Persisted flag then cancelled | Submit again to process remaining eligible games |

The API binds to 127.0.0.1, has no arbitrary/live-position endpoint, and rejects
mutations with nonlocal browser origins. Supported frontend ports are 5173 and
4173; API docs use 8000. Do not expose this unauthenticated local service publicly.
Liveness `/health` is independent of `/api/v1/analysis-worker` readiness.

## Tests and diagnostics

Normal checks never require Stockfish or Ollama:

```sh
uv run ruff check .
uv run mypy src
uv run pytest
cd frontend
pnpm lint
pnpm check
pnpm test
pnpm build
pnpm test:e2e
```

Install the required browser once using `pnpm test:setup`; tests do not install
anything. Real-engine adapter checks are opt-in: `uv run pytest -m engine`.
The real full-stack browser demonstration is also opt-in:

```sh
cd frontend
PHASE10_REAL=1 pnpm test:e2e analysis-real.e2e.ts
```

It uses ten PGNs from `data/phase10-before.db` in a new temporary database and
requires port 8000 to be free. It starts/cleans up its API and worker, submits from
the UI, kills/restarts the worker, closes/reopens the page, verifies repeat skips,
and changes the node budget. Screenshots go to ignored local `data/` artifacts.
See the [measured baseline](../benchmarks/phase10-baseline.md) for separate
throughput and deterministic hard-stop reproduction commands.

Regenerate API types after schema changes:

```sh
uv run python scripts/generate_api_types.py
cd frontend && pnpm exec prettier --write src/lib/api/generated.ts
```

Do not hand-edit generated types. Migration downgrade refuses to discard new
profile evidence; use the pre-migration backup for a deliberate rollback.
