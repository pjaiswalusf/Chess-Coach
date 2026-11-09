# Phase 20 reliability report

Verified on November 9, 2026 with the repository's Python 3.14 environment.

## Test isolation

Pytest uses per-test SQLite paths. API and persistence tests apply the real
Alembic migrations. Standard tests intercept real HTTPX transports, and the
default Stockfish path points to a missing file. Stockfish and Ollama smoke tests
require explicit opt-in.

Playwright starts the Svelte build preview on `127.0.0.1:4173`. The complete
workflow starts FastAPI on `127.0.0.1:8001` against a new migrated SQLite file.
The browser test checks the fixture's unique response header through Vite before
making mutations. Fault controls are files in the temporary test directory. The
fixture uses the real HTTP routes, persistence, sync, analysis, coaching and
puzzle use cases with an offline source transport, engine and model. A separate
pytest test exercises the production analysis worker as an OS process.

The personal database baseline was 646 stored games, all 646 awaiting PGN
validation, zero completed game analyses and zero puzzles. SHA-256 checks covered
the database and WAL files. An early fixture startup consulted the default
database in read-only mode because settings were cached before the fixture
selected its database. Readiness halted that attempt before any browser writes.
The fixture now clears cached settings before startup, and fault injection
targeted disposable databases.

## Behavior and evidence

| Scenario | Evidence |
| --- | --- |
| Liveness, readiness and component status | `test_liveness_and_readiness_skip_optional_probes`, `test_system_optional_probe_cache_expires_without_affecting_readiness`, `test_missing_stockfish_rejects_new_run_and_preserves_analysis`. The legacy `/health` contract is preserved. Readiness returns `503` for a database failure. Chess.com status is `not_checked`. Stockfish and Ollama probes have individual two-second time limits and a five-second result cache on the system summary. |
| Database failure and incompatible schema | `test_unavailable_database_is_visible_without_fabricated_statistics`, `test_migration_stamp_without_required_tables_is_not_ready`, `test_old_schema_blocks_analysis_but_liveness_remains`. Corrupt SQLite and an unusable parent produce actionable responses. The system report leaves statistics absent. |
| Chess.com timeout and recovery | `test_source_failure_is_durable_and_retry_preserves_history`. Three attempts, persisted `CHESSCOM_TIMEOUT`, unchanged existing IDs and PGNs, successful retry and zero duplicate inserts. |
| Chess.com rate limit | `test_rate_limit_clears_on_last_attempt_without_duplicate_games`, `test_retry_after`, `test_exhausted_rate_limit_stops_scan_and_preserves_committed_month`. A final `429` ends that scan. A retry hint over 30 seconds ends the request immediately. Completed archives retain their checkpoints. |
| Missing or failing Stockfish | `test_missing_stockfish_rejects_new_run_and_preserves_analysis`, `test_engine_failure_retries_once_then_fails_run`. Admission without an available worker returns `503 WORKER_UNAVAILABLE`. A mid-game failure preserves earlier move rows, publishes zero partial move rows, and lets a new run reuse cached positions. |
| Abrupt and graceful analysis recovery | `test_worker_signal_recovers_ten_games` uses both `SIGKILL` and `SIGTERM` after three game commits and a fourth-game position checkpoint. Restart resumes the same run. There are ten completed games, 40 unique move rows, nine engine evaluations and 43 cache hits across the two process attempts. Only the interrupted game has two processing attempts. Both runs return `ok` from SQLite `integrity_check` and zero rows from `foreign_key_check`. The graceful path verifies engine cleanup. |
| Ollama unavailable, invalid or contradictory | `test_vertical_slice_cache_duplicate_and_offline`, `test_invalid_output_never_success`, `test_known_contradiction_rejected_and_corrupt_cache_regenerates`, `test_restart_and_failed_request_retry`. Stored reports and deterministic evidence remain readable. An uncached request returns `503 OLLAMA_UNAVAILABLE`. The structured schema, fact checks and bounded retry reject covered output failures. |
| Malformed PGN isolation | `test_bad_pgn_quarantines_only_its_own_record`, `test_mixed_batch_idempotent_and_explicit_retry`, `test_strict_boundary`, `test_legal_underpromotion_from_fen`. An empty or broken Result header with valid source metadata leaves four valid games committed. Illegal movetext is quarantined at the parsing stage. Repeated processing adds zero game duplicates. |
| Concurrent job submission | `test_same_operation_double_submission` and `test_cross_operation_double_submission_persists_one_run`. Each pair of simultaneous requests yields one `202`, one `409`, and one database run. |
| Browser workflow, disconnect and API restart | `complete-workflow.spec.ts`. The browser sees actionable timeout and rate-limit messages, imports completed games, displays the quarantined PGN count, closes its tab during a paused analysis and reconnects after completion. Game review shows the board, the critical move and its evaluation. Coaching shows measured evidence and saves the generated report. Training grades and persists a correct attempt. The test stops FastAPI, sees the recovery control, restarts, and verifies the report and attempt remain available with the model offline. It asserts zero uncaught page exceptions. |
| Local-only and post-game safety | `test_cli_serves_api_on_loopback`, `test_security_errors_and_unexpected_exception`, `test_variants_and_incomplete_results`, `test_strict_boundary`, `test_analysis_rejects_unsupported_version_and_malformed_json`. The configured listeners bind to loopback. Import requires terminal completion evidence and analysis uses validated stored games. |

## Verification runs

| Check | Result |
| --- | --- |
| Standard pytest | 705 passed on each of three consecutive runs. Each run skipped the opt-in Ollama case and deselected three Stockfish smoke tests. |
| Real Stockfish smoke | 3 passed. |
| Overall coverage | 88.30% branch-aware, above the 80% gate. Line coverage was 5,481 / 6,086 (90.06%) and branch coverage was 1,246 / 1,532 (81.33%). |
| Core coverage | 91.70% branch-aware, above the 90% gate. Line coverage was 1,402 / 1,495 (93.78%) and branch coverage was 431 / 504 (85.52%). |
| Ruff and mypy | Passed. |
| Frontend lint, type check and build | Passed. Each Playwright pass built the production frontend. |
| Vitest | 37 passed. |
| Playwright | 39 passed on each of two consecutive runs, including the full offline workflow. Three legacy opt-in tests were skipped in each default run. |
| Real Stockfish browser recovery | `PHASE10_REAL=1 pnpm test:e2e analysis-real.e2e.ts` passed after adding a fixture-identity check through Vite. |
| SQLite integrity and foreign keys | Passed after both recovery signals. The personal database and WAL fingerprints matched the baseline. |

Branch-aware coverage is covered statements plus covered branch destinations
divided by the corresponding total. The core gate covers all of
`chess_coach.analytics` plus `domain.analysis`, `domain.score_utils`,
`domain.training`, `domain.review_schedule`, `application.analysis`,
`analysis_worker` and `infrastructure.persistence.analysis_repository` in the
`chess_coach` package. The overall HTML report is generated in `htmlcov/`.

## Scope of the evidence

The coaching checks verify structured references, preserve engine facts, and
reject detectable contradictions. Free-text claims outside the validator's
patterns can escape detection. Model quality and sustained performance require
their separate evaluation and benchmarking runs.

The browser suite uses a deterministic model and fixture engine. The opt-in
Stockfish smoke suite covers real UCI behavior. The opt-in real Ollama test is
separate from the Phase 20 offline gate and was skipped. The browser fixture
exercises the sync use case through its own job loop. Recovery of the production
analysis worker is covered by the subprocess tests.

## Independent review

The read-only reviewer followed `.cursor/agents/reviewer.md` at each batch
boundary and in the final audit. The final result was PASS for all fourteen
review areas. The review verified three matching backend runs and the coverage
measurements, checked the personal database fingerprints, and reviewed the
browser evidence and fixture isolation.

Review fixes included a safe response for an unusable database directory,
schema checks for missing tables, stopping a scan after a final rate limit,
isolating empty or corrupt PGNs within an archive, and requiring server identity
checks before browser writes. The final review closed all P0 and P1 findings and
gave a GO for Phase 21 after the Phase 20 commit.
