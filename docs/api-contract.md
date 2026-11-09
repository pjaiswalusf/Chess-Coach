# Phase 13 HTTP contract

This API serves completed historical games only. It never accepts a live position,
engine executable, database path, or per-request engine budget. The supported
launcher is `uv run chess-coach serve`, bound to **127.0.0.1:8000**. Apply existing
migrations with `uv run alembic upgrade head` before starting database operations.
No new migration or dependency is required for Phase 13.

## Operations

| Method | Path | Success | Application implementation |
| --- | --- | --- | --- |
| GET | `/health` | 200 | Dependency-free liveness |
| GET | `/api/v1/system` | 200 | `system_report`, `QueryRepository.statistics`, bounded probes |
| GET | `/api/v1/player` | 200 | `QueryService.player` |
| PUT | `/api/v1/player` | 200 | `QueryService.set_player` |
| POST | `/api/v1/sync-runs` | 202 | `JobService.start_sync`, `SyncRepository.enqueue` |
| GET | `/api/v1/sync-runs/{run_id}` | 200 | `JobService.sync_progress` |
| GET | `/api/v1/games` | 200 | `QueryService.games` |
| GET | `/api/v1/games/{game_id}` | 200 | `QueryService.game` |
| GET | `/api/v1/games/{game_id}/analysis` | 200 | `QueryService.game_analysis` |
| POST | `/api/v1/analysis-runs` | 202 | Existing `AnalysisService.create` |
| GET | `/api/v1/analysis-runs/{run_id}` | 200 | Existing `AnalysisService.detail` |
| GET | `/api/v1/analytics/summary` | 200 | Existing `AnalyticsService.build_report`, overall projection |
| GET | `/api/v1/analytics/openings` | 200 | Same report, opening projection |
| GET | `/api/v1/analytics/phases` | 200 | Same report, phase projection |
| GET | `/api/v1/analytics/patterns` | 200 | Same report, weakness/context projection |
| GET | `/docs` | 200 | Generated interactive documentation |
| GET | `/openapi.json` | 200 | Generated machine contract |

Existing diagnostic extensions remain: `GET /api/v1/system/status`,
`GET /api/v1/analysis-worker`, `GET /api/v1/analysis-runs`, and
`POST /api/v1/analysis-runs/{run_id}/cancel`. They are documented in OpenAPI.
The old game-analysis bare array is now `{game_id, status, profile_hash,
engine_version, analysis_version, moves}`; the existing frontend client is updated.

## Phase 17 product UI extensions

- `PUT /player` with `verify: true` checks the public Chess.com profile with a
  bounded request before first binding the library. A missing player returns
  `PLAYER_NOT_FOUND`; a failed verification leaves the library unconfigured.
  The browser uses verification, while the legacy local configuration contract
  still accepts an omitted flag. Neither variant starts an import.
- `GET /sync-runs/latest-work` returns the latest tracked-player IDs, preferring
  active runs, so reload and ambiguous admission responses can be reconciled by
  reading the database. Sync progress exposes `partial` and
  `progress.games_skipped`. `GET /analysis-runs/{run_id}/progress` includes
  `games_remaining` and omits the per-game member list.
- `GET /games` accepts `result=win|loss|draw`. Page items show the tracked
  player's rating and a nullable critical-error count for the current profile,
  using only the player's classifiable stored moves. The list checks source
  identity and move count; review performs deep legality and history validation.
  The review response adds `initial_fen` and each move's `fen_after` and
  backend severity. No frontend chess replay is required.
- `GET /analytics/overview` returns the dashboard projections from one report
  snapshot. The overview and patterns responses include supported conversion and
  trend evidence (see [analytics policy](ANALYTICS.md)). Patterns exposes a stable
  `report_hash`; POST to `/coaching/history` can send
  `expected_report_hash` to reject changed evidence with `COACHING_REPORT_CHANGED`
  before checking Ollama or admitting work.
- `GET /system` also reports configured model readiness, cache size, active work
  counts, and analysis version. Vite binds to loopback with CORS disabled in
  both dev and preview.

## Shared conventions and errors

JSON bodies; UTC ISO 8601 timestamps (nullable when not known); positive database
integer IDs; missing ratings and metadata remain null. Successful responses use
explicit endpoint schemas, without a universal envelope. All errors have shape:

```json
{"code":"GAME_NOT_FOUND","message":"The requested game was not found.","details":{}}
```

Known errors: 400 `HOST_NOT_ALLOWED`; 403 `ORIGIN_NOT_ALLOWED`; 404
`GAME_NOT_FOUND`, `RUN_NOT_FOUND`, `SYNC_RUN_NOT_FOUND`; 409
`PLAYER_NOT_CONFIGURED`, `PLAYER_SWITCH_UNSUPPORTED`, `MULTIPLE_PLAYERS`,
`PLAYER_MISMATCH`, `SYNC_ALREADY_RUNNING`, `ANALYSIS_ALREADY_RUNNING`;
422 `VALIDATION_ERROR`; 503 `WORKER_UNAVAILABLE`, `DATABASE_UNAVAILABLE`;
500 `INTERNAL_ERROR`. Existing analysis errors retain their stable codes.
Validation details contain field locations and error categories, never request
values. Unexpected failures and database diagnostics are logged server-side;
paths, prompts, PGNs and exception strings are not returned in errors.

Public run `status`: `queued`, `running`, `completed`, `failed`. Pending maps to
queued; done/succeeded maps to completed; cancelled, partial and
completed-with-errors map to failed. Analysis retains `storage_status`, counters,
and `cancel_requested` to distinguish those terminal cases without hiding partial
success. It also retains `id` for the existing UI and adds synonymous `run_id`.
Member-game statuses in analysis progress remain the stored pending/running/done/
failed/skipped vocabulary. A run GET reads persisted state; it never recovers work.

## Player and games

`GET /player`: `{configured:false, player:null}` when empty, otherwise
`{configured:true, player:{id,platform,username}}`. `PUT /player` accepts
`{"platform":"chess.com","username":"example_player"}` (platform defaults to
chess.com), forbids extra fields, and uses the existing import identity validator:
1–100 ASCII letters/digits/underscore/hyphen, trimmed and lowercased. This is an
import-compatible identity policy, not account creation validation or proof of a
real upstream account. Sync verifies upstream identity. Setting the same player is
idempotent. Switching to another player is deliberately unsupported (409), history
is preserved, and no PUT starts a network request. Existing databases with multiple
Chess.com players must use the CLI; the API does not guess an active account.

`GET /games`: `limit=20` (1–100), `offset=0` (>=0), optional `time_class`
(bullet/blitz/rapid/daily), `player_color` (white/black), `analysis_status`
(pending/running/completed/failed). Order is played_at DESC, id DESC. Returns
`{items,total,limit,offset}`; items omit PGN and moves. The page and total apply the
same filters. Empty database: 200 with empty items. Only configured-player games
are returned. The list/detail `analysis_status` is a persisted processing status for the
selected current profile; its filter uses that same status. It does not certify
current evidence compatibility. The analysis endpoint additionally checks source
hashes and deep legality/history evidence, returning incompatible when needed.

Detail returns players, nullable ratings/opening/time control, player color,
result, raw PGN and completion provenance. PGN imports trust the declared result
(`pgn_declaration`); Chess.com imports use `chesscom_archive`. Provenance does not
assert checkmate. Missing game: 404; invalid ID: 422.

Game analysis defaults to the registered worker's profile, or the latest stored
analysis-run profile if no worker registration exists. Optional `profile_hash`
selects an explicit 64-character hex profile. No results are mixed between profiles.
Unknown/incomplete analysis is pending/running/failed with empty moves; invalid
completed evidence is `incompatible` with empty moves. A completed response uses
persisted ordered move evidence after existing legality/history compatibility
validation. `eval_before_cp_white`/`eval_after_cp_white`: positive favors White.
`loss_cp`: deterioration from the mover's perspective, never blindly White's.
Mate distances/winner colors are separate; mate transitions have null numeric
loss. No game/analysis GET starts an engine, model, import, or queue operation.

## Jobs and recovery

Run the local workers in separate terminals:

```sh
uv run chess-coach sync-worker
uv run chess-coach analysis-worker
```

`POST /sync-runs` accepts `{}` and persists a queued ImportRun before returning
`{run_id,status:"queued"}`. The polling sync worker invokes the existing
`SyncGamesService` on this same run ID; acceptance does not require an already
running worker. A stopped worker leaves a durable queue. It validates newly
imported PGNs under the held sync lock before publishing terminal completion.
Progress includes nullable archives_total, archives_processed, games_seen,
games_inserted, games_existing and games_failed. Archive totals are unknown until
upstream discovery completes. Errors are safe summaries; archive diagnostics
remain in backend logs/persistence. Partial imports map to failed with retained
counts. On restart, under the kernel sync lock, running imports become failed and
recoverable; start another sync to reuse successful archive checkpoints. Queued
imports retain their original IDs and execute when the worker returns.

`POST /analysis-runs` accepts `{"scope":"pending"}` or `{}`. Optional
`tracked_player_id` is retained for the existing frontend and must match the one
configured player. Extra engine settings and force-reanalysis flags return 422.
The verified local worker must be available or admission returns 503.
The existing repository excludes unparsed/incompatible-parser source games and
skips compatible completed evidence. A no-work run completes immediately without
engine work. Existing counters distinguish completed, failed, skipped and excluded
games; completed + failed + skipped <= games_total. Skipped games count as
successful existing evidence, never newly completed work. The dedicated worker
resumes interrupted analysis using its existing recovery and history-sensitive
cache logic. Poll 1–2 seconds while active; stop at terminal state.

Both admissions reserve SQLite's writer transaction **before** checking active
sync and analysis runs. This enforces cross-operation exclusion across requests
and processes, including legacy CLI sync/analysis admission. Kernel locks prevent
concurrent sync executors and concurrent analysis engine workers. Closing a browser
or restarting the API does not remove persisted jobs. A worker must actually run
for a queued job to progress. No Redis, Celery or in-memory job-only state is used.

## Analytics

All four endpoints share `window=last_50` (last_20/last_50/last_100/all),
`color=all` (white/black/all), `time_class=all`
(bullet/blitz/rapid/daily/all), and optional `profile_hash` as above. Filters apply
before selecting the last N games; unanalysed members are retained in the cohort.
Unknown enum values return 422. Time class means category, never raw clock control.

Responses share filters, resolved profile_hash, status, analytics_version,
policy_version, selected_game_ids and health/coverage. Summary returns `metrics`;
openings/phases return `items`; patterns returns category-specific `patterns`,
`contexts`, and ranker_version. With no configured player, status is NO_GAMES,
health/metrics are null and collections are empty. A configured player with no
analysis profile still gets stored outcomes; engine evidence remains unavailable.
Analytics status retains the existing deterministic report enum:
COMPLETE/PARTIAL/INSUFFICIENT_DATA/DATA_ERROR/NO_GAMES (distinct from run status).

The existing nested `Summary`, `MoveMetrics`, `Rate`, `Segment` and `Weakness`
schemas are reused without recomputing formulas in HTTP handlers. Rates expose
numerator, denominator and per_100. `score_percentage` = 100*(wins+0.5*draws)/games;
`win_rate` counts wins only. Mean CP loss excludes missing scores/mate transitions;
severity rates divide by classifiable analyzed player moves. Coverage explicitly
separates selected from analyzed games/moves. Zero denominators produce null rates.
See [analytics definitions and sample policy](ANALYTICS.md) for all thresholds.
Unknown phases remain unclassified. Small cohorts expose insufficient evidence;
unsupported rankings are suppressed. Weakness source_moves identify game/ply;
priority_score is a versioned heuristic, not a probability or causal conclusion.
Reads start no upstream lookup, engine search, inference, or writes. Validated
engine evidence can supply transient deterministic features when snapshots are absent.
Existing analytics may validate/replay stored evidence, so all-history reads can be
slow: no Phase 13 latency guarantee or cache is claimed.

## System, liveness and local safeguards

`/health` returns only `{"status":"ok"}` independently of all dependencies.
`/system` returns status healthy/degraded/unavailable, database/stockfish/ollama
components, nullable statistics, and checked_at. Ollama model comes from Settings.
Its service probe has a 1-second HTTP timeout. Stockfish executable detection is
lightweight: a found executable alone reports unknown, not verified readiness. An available
registered worker supplies verified availability and engine version in `/system`;
`/analysis-worker` also exposes its heartbeat.
No system poll launches Stockfish. Missing executable reports unavailable.
Database status uses a local read with a 250ms SQLite lock timeout; unavailable
statistics are null, never fabricated zeroes. Counts use current-profile persisted
completion/source/move-count checks, not a costly full-history engine-cache replay.
Per-game analysis reads perform deep validation. Read-only compatibility checks
are still CPU work; these timeouts are not a hard wall-clock deadline for arbitrary
database sizes. No p95 performance budget is claimed as measured here.

Requests accept localhost/127.0.0.1/::1 Host values only. Mutating browser requests
must have an allowed http Origin on localhost/127.0.0.1 ports 5173/4173/8000;
opaque or remote origins and cross-site Fetch Metadata are rejected. Origin-less
local CLI clients remain supported; this is a single-user local boundary, not
account authentication. JSON validation rejects simple form/text mutation bodies.
No permissive CORS middleware is installed. The Vite `/api` development proxy
preserves backend status and JSON; frontend API code uses relative `/api/v1` URLs.

## Existing-service inventory and changes

| Capability before Phase 13 | Existing entry point | Inputs/output, cost, readiness |
| --- | --- | --- |
| Player | `AnalysisRepository.players`, sync player creation | Sync SQL, IDs/names; no active-player update/query service. Added QueryService; switching unsupported. |
| Sync | `SyncGamesService.sync` / `SyncRepository` | Username/options -> SyncReport, synchronous network/DB expensive; resumable archive checkpoints. Added durable admission/claim and serial worker; reused archive implementation. |
| Game queries | Existing Game storage, no application query service | Added bounded QueryRepository/QueryService projections; synchronous local SQL. |
| Move analysis | `AnalysisService.moves` | game_id/profile -> persisted dictionaries; read-only. Reused compatibility validator with explicit game envelope/not-found behavior. |
| Analysis | `AnalysisService.create/detail`, `AnalysisRepository`, `run_worker` | Player ID -> persisted run, sync short admission; dedicated expensive worker. Added shared cross-operation admission and public status mapping. |
| Analytics | `AnalyticsService.build_report` / `AnalyticsRepository.load` | AnalyticsRequest -> validated AnalyticsReport; sync read/replay/aggregation; reused unchanged calculations. |
| Infrastructure | `collect_system_status`, `probe_ollama`, `probe_stockfish` | Sync typed readiness; bounded network/subprocess probes. API uses lightweight executable detection instead of repeated UCI startup; added DB statistics report. |

Dependencies are injected with FastAPI Depends and replaceable in tests. Sessions
and engines are disposed after request use. Routes validate, delegate and project
typed results; SQL, admission, chess validation and aggregation remain outside API
routes. No frontend dashboard, coaching generation, or future-phase endpoint is added.
