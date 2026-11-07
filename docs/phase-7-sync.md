# Resilient Chess.com ingestion

Phase 7 implements local completed-game ingestion using the existing Python 3.14,
HTTPX, SQLAlchemy, Alembic and SQLite stack. No new dependencies were needed.
The original supplied roadmap is in [phase-7-plan.md](phase-7-plan.md); its Python
3.12 and assumed tenacity references do not override the repository configuration.
The exact implemented behavior is in [sync-contract.md](sync-contract.md).

## Usage

```sh
uv run alembic upgrade head
uv run chess-coach sync --username YOUR_NAME --dry-run
uv run chess-coach sync --username YOUR_NAME --month 2026/06
uv run chess-coach sync --username YOUR_NAME
uv run chess-coach sync --username YOUR_NAME --force
uv run chess-coach sync-status --username YOUR_NAME
```

Use `CHESS_COACH_DATABASE_PATH` to select a different local database. Upgrade that
same database before use. `chess-coach` with no arguments still serves the API;
`chess-coach serve` is explicit. Sync exits nonzero for partial/failed results.
No credentials are needed. The CLI JSON report is also retained in
`import_runs.summary_json`; start/end timestamps supply run duration.

## HTTP and refresh policy

Only these endpoints on `https://api.chess.com/pub` are used:

- `/player/{username}`
- `/player/{username}/games/archives`
- `/player/{username}/games/{YYYY}/{MM}`

One reusable synchronous client, TLS verification on, redirects off, recognizable
User-Agent. Timeouts: connect/write/pool 5 seconds, read 20 seconds. At most three
attempts for timeout/network errors, 429 and 5xx; waits are 1 then 2 seconds plus
0–1 seconds jitter. Retry-After accepts integer seconds or HTTP dates; delays over
30 seconds fail explicitly. No retries for ordinary 4xx, invalid JSON/schema,
or redirects. Profile 404/410 is PLAYER_NOT_FOUND; archive 404/410 is UNAVAILABLE.
An unconditional 304 gets one unconditional retry, then fails. Conditional 304
requires a complete committed checkpoint with a sent validator. ETag takes
precedence over Last-Modified. Successful empty archives are valid.

Archive URLs must exactly match the HTTPS API host, requested username and monthly
path; query strings, fragments, foreign hosts, malformed and future dates fail.
URLs are reduced to dates, deduplicated, sorted and reconstructed by the client.
The archive month is not assumed to equal each game's UTC end month: live source
verification demonstrated boundary games ending the next month.

Refresh current and previous UTC months plus missing/failed/interrupted archives.
Skip complete older months. `--force` revalidates every selected archive, including
unavailable ones, without deleting games. Successfully imported historical data
can change upstream; deliberate forced rescans are the recovery path.

Reference: [official Chess.com PubAPI documentation](https://www.chess.com/news/view/published-data-api)
for endpoints, result codes, serial access, caching and response semantics. API/CDN
lag means newly completed games may not be visible immediately.

## Identity and persistence

Preferred external identity is `uuid:<canonical UUID>`; if absent,
`url:<validated game URL>`. URLs are restricted to
`https://www.chess.com/game/(live|daily)/<positive integer>`.
A stable URL is required in both cases. The Phase 7 `canonical_hash` value is
SHA-256 of UTF-8 `chesscom-source-v1:<URL>`, not a normalized PGN hash.
DB uniqueness on `(platform, external_id)` and `canonical_hash` handles both UUID
and URL fallback. A conflict preserves the original game row. Existing schema's
global identity means a shared game belongs to its first tracked player.

This deliberately source-specific hash supersedes the *planned* Phase 6 hash for
Chess.com ingestion only. Cross-source PGN deduplication is not claimed; Phase 8
needs an explicit migration/compatibility decision. No record is accepted without
stable source identity. Source PGN is retained byte-for-byte as decoded JSON text.
Phase 7 validates completion metadata and Result headers but does not parse or
replay the PGN; legal replay remains a prerequisite for future analysis.

Migration `c7a001` adds archive_sync_state, import_rejections, and nullable run
summary JSON while preserving Phase 6 rows. All month records validate before the
transaction. Games, successful checkpoint, HTTP validators and run counters commit
atomically. Invalid supported records prevent all game inserts for that month;
rejected PGNs and diagnostics persist separately, with a failed checkpoint.
Unsupported variants are explicit skips and do not fail otherwise valid archives.

## Recovery and diagnostics

A database-wide nonblocking OS file lock serializes local imports, including
separate CLI processes. This is stricter than per-player exclusion and keeps all
archive HTTP requests serial for this local database. macOS/Linux are supported;
Windows would need a different OS lock adapter. Use one database per local worker;
separate database files do not coordinate requests. Never remove a lock file while
an importer is running. File existence does not mean the kernel lock is held.

The kernel releases locks on termination, including SIGKILL. The next real sync
recovers durable RUNNING jobs and archives after acquiring the lock; completed
months remain complete. Previous errors and counters survive recovery. A crashed
run with successful checks is PARTIAL even when it inserted zero games. Dry runs
inspect stale state but do not recover or mutate it.

`/health` remains process health, without upstream calls. `sync-status` checks the
database and shows game count, grouped archive states, last report and error without
network access. `sync --dry-run` is an explicit upstream profile/discovery probe.
A failed source request is never interpreted as an empty archive. Structured log
records carry run/archive IDs; database exception parameters are hidden to avoid
logging PGNs. Database failures suggest migration/access checks.

## Verification procedure

Run Ruff, mypy and pytest; use coverage to diagnose missing tests:

```sh
uv run ruff check .
uv run mypy src
uv run pytest --cov=chess_coach --cov-report=term-missing --cov-report=json
uv run alembic check
```

Tests use MockTransport and temporary migrated SQLite files. They cover transport
errors/retry limits, safe URL discovery, 304/404/410/429/5xx, identity fallback,
source validation, UTC month planning, 7→7→8 inserts, immutable existing games,
partial failures, rollback, interruption, overlapping processes and SIGKILL lock
release, dry runs, diagnostics and CLI failures. Core importer coverage comprises
`domain/sync.py`, `application/sync_games.py`, `infrastructure/chesscom/*.py`, and
`infrastructure/persistence/sync_repository.py`.

Live verification: choose one listed historical month, import it, compare several
stored URLs/raw PGNs/usernames/timestamps independently to the source, then import
all history and immediately repeat. Record counts and elapsed time, and verify
zero duplicate rows and no unnecessary historical downloads. See the verification
record below for actual outcomes; fixture results are not live performance claims.

## Verification record — 2026-11-07

- Python 3.14.6; initial baseline 107 tests passed and Phase 6 migration was current.
- Final Ruff and mypy passed; 184 tests passed. Alembic schema drift check passed;
  migrated temporary database upgrade/downgrade/re-upgrade tests passed.
- Backend line coverage: 814/849 = 95.9%. Core importer subset above:
  450/462 = 97.4%. Generated coverage.json is local/ignored.
- Independent read-only review followed `.cursor/agents/reviewer.md`: PASS after
  fixing identity-presence transitions, recovery of zero-insert successful checks,
  obvious invalid PGNs, preserved rejection reasons and cross-process lock tests.
- Authorized live account `pjaiswal49`: six archives, June–November 2026.
  June smoke imported 30 games (run 1, 0.773 seconds inside persisted run).
  Independent HTTP source comparison of five games matched URLs, exact PGNs,
  both player names and UTC end timestamps.
- First full-history attempt (run 2, 3.915 seconds) inserted 313 additional games
  but conservatively rejected July and September on an invalid month-equality
  assumption. A repeat (run 3, 0.750 seconds) inserted none and accurately remained
  partial. The source contained six boundary games ending in the next UTC month;
  the unsupported assumption was removed and covered by a regression test.
- Recovery run 4 completed: fetched four archives, skipped two, two 304s,
  received/inserted 303 games, zero failures (2.294 seconds).
- Immediate run 5 completed: four historical archives skipped, two conditional
  304 checks, zero games received/inserted, zero failures (0.100 seconds).
- Final database: 646 games, 646 distinct external IDs, 646 distinct fingerprints;
  all six archive checkpoints complete. Earlier partial-run diagnostics remain
  available, rather than being rewritten as successful history.

Durations above exclude profile preflight and process startup, and describe this
cached live verification only. They are not engine benchmarks or general throughput
claims. There was no clean single-run full-history benchmark after the correction;
completed checkpoint/retry behavior and the final repeat were verified directly.

Known limits: no Windows lock adapter, no cross-database request coordination, no
source account-rename reconciliation, no cross-source PGN deduplication, and no
full PGN syntax/position/legal-move verification until Phase 8. Source rows are
completed-game ingestion evidence, not yet legally replayed analysis inputs.
