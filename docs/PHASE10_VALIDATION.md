# Phase 10 validation record

Completed 2026-11-08 on branch `feat/analysis-pipeline`.

## Session outcomes

| Session | Delivered |
| --- | --- |
| A — preflight/lifecycle/eligibility | Baseline 284 tests passed; SQLite backup created; existing tables extended through Alembic; persistent status transitions, stable membership, profile-specific eligibility, exclusion and progress reporting |
| B — positions/cache | N+1 history-preserving contexts; validated White-oriented score/PV evidence; separate mate winner; compatible cache and unknown-history policy; one configured search budget |
| C — measurements/deep-pass decision | Real 10/30-game throughput measured. Candidate/deep/MultiPV work deliberately deferred: no measured need or labeled quality evidence justifies multiple passes. Single-pass estimates remain explicitly provisional. |
| D — atomic persistence | Required positions validated; move rows and completion state committed together; cache survives partial work; profile-specific uniqueness; isolated game failures |
| E — worker/API/UI/recovery | Dedicated single worker; kernel lock plus serialized DB claims; cancellation/retry; recovery; safe errors; generated API types; Svelte polling and persisted move evidence |
| F — safety/verification/operations | Bounded engine retry, disk preflight, database retry, local-origin protection, structured timings, regression/failure tests, real SIGKILL and full-stack tests, measured baseline and runbook |

## Final commands and results

| Check | Result |
| --- | --- |
| `uv run ruff check .` | Passed |
| `uv run mypy src` | Passed, 51 source files |
| `uv run pytest --cov=chess_coach --cov-report=json --cov-report=term -q` | 329 passed; 2 real-engine tests excluded as intended |
| `uv run pytest -m engine -q` | 2 passed |
| `pnpm lint` | Passed |
| `pnpm check` | Passed, zero errors/warnings |
| `pnpm test` | 5 passed |
| `pnpm build` | Passed |
| `pnpm test:e2e` | 3 passed; opt-in real test skipped as intended |
| `PHASE10_REAL=1 pnpm test:e2e analysis-real.e2e.ts` | 1 passed, 23.3-second test / 25.5-second command |
| `git diff --check` | Passed |

Normal tests use deterministic adapters and migrated temporary SQLite databases;
they require neither public networks, Ollama, nor a Stockfish installation.
Chromium was installed separately with the existing `pnpm test:setup` command.
There were no new dependencies.

## Reliability evidence

- Equivalent repeat runs perform zero searches; exact cache reuse is tested
  separately using shared position histories.
- Incompatible nodes, engine identities, and full/unknown histories cannot reuse
  old results. Changed profiles preserve prior move evidence.
- Missing move rows make a game eligible again; malformed/corrupt PV evidence
  fails validation. Incomplete evidence cannot be returned as a valid completion.
- White/Black loss orientation and mate-zero winner handling are tested. Mate
  never enters CP arithmetic. Claimable versus automatic repetition is tested.
- Insertion failure rolls back all game-level rows while retaining valid cached
  positions. Invalid games do not stop later games.
- Concurrent submissions produce one accepted run. A second worker cannot acquire
  the database's kernel lock. Disk preflight and worker cleanup are tested.
- A real subprocess was killed with SIGKILL after exactly three games. Its 119
  committed move rows survived. Restart produced 10 completed games / 445 rows,
  no duplicate keys, and zero searches on an equivalent subsequent run.
- The real browser test starts analysis from Svelte, kills the worker mid-batch,
  closes the page, restarts the worker, reopens the page, waits for completion,
  repeats without searches, changes nodes from 10000 to 20000, completes a distinct
  profile, and renders actual move evidence through the API. Its temporary API
  and worker processes are cleaned up.
- The full-stack test exposed a real configuration defect: strict integer settings
  rejected environment strings for node budgets. The fix accepts decimal strings
  while continuing to reject booleans/fractional values; regression tests cover it.

## Coverage diagnostics

All production modules, including unimported drafts, are included:
**2002 / 2157 executable lines = 92.81% overall**.

Deterministic core subset: **442 / 461 = 95.88%**, comprising:

- `domain/analysis.py`
- `domain/engine_types.py`
- `domain/game_records.py`
- `domain/score_utils.py`
- `domain/sync.py`
- `infrastructure/pgn/parser.py`
- `infrastructure/chesscom/normalization.py`

No analytics implementation or LLM quality result is claimed. The engine adapter
has 94% normal-suite coverage; actual engine behavior is tested separately.

## Data and operational state

The preflight SQLite backup is local and ignored: `data/phase10-before.db`.
The live local database was upgraded from c7a001 to 2f6cd65e0963 after migration
checks passed. All **646** original IDs, raw PGNs, platform identities, external
IDs and canonical hashes match the backup exactly. SQLite integrity check is
`ok`, and foreign-key check returns no violations.

All 646 legacy rows lack stored source evidence and remain pending validation.
They were not silently treated as verified completed Chess.com games. Refresh
source evidence and revalidate using the commands in the
[runbook](operations/analysis-runbook.md) before analyzing those records.
Benchmarks and crash demonstrations used isolated databases, not the live one.

## Limits and non-blocking tool messages

Stockfish results remain search estimates. No quality study justifies definitive
mistake labels, candidate/deep passes, or MultiPV. Peak memory was not measured.
The benchmark samples are historical first-N subsets, not random quality samples.

Existing upstream messages remain: python-chess asyncio deprecations, a
SvelteKit/Vitest transform hook warning, and adapter-auto's unsupported production
hosting notice. All relevant commands pass; this phase supports the documented
local Vite/API workflow, not a new production hosting deployment.

See [measured results](benchmarks/phase10-baseline.md) and
[operations/recovery](operations/analysis-runbook.md).
