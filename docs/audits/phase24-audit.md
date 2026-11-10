# Phase 24 — engineering audit and repair

## 1. Executive summary

**Overall: PARTIALLY VERIFIED. Recommendation: CONDITIONAL — usable, not fully portfolio-ready.**

Executed on 10 November 2026 (Asia/Kolkata). The initial working tree was clean.
The audit found seven issues: two P1 and five P2. Four received focused repairs;
three remain (human-reviewed quality, model comparison and the strict benchmark
rejection rate).
Remote CI verification is an additional access blocker, not an observed CI failure.
No P0 was found. Highest remaining finding severity: P2.

The controlled data, chess and end-to-end workflows pass. Real Stockfish and
local Ollama ran. A schema-valid output is not proof of factual or useful advice.
The AI-grounding and engineering-reproducibility release gates remain incomplete;
this is not an overall portfolio PASS.

## 2. Environment and safety baseline

| Item | Observed |
| --- | --- |
| Repository | `/Users/pratikjaiswal/Documents/GitHub/Chess-Coach` |
| Initial branch / revision | `chore/phase-23-ci-portfolio` / `c13192c75531d4f3ff4c51b77375dbbb98e4dadc` |
| Initial Git state | Clean; no pre-existing tracked modifications or untracked files reported |
| Hardware | Apple M5, Mac17,3, arm64, 16 GiB memory |
| OS | macOS 27.0.1, build 26A434 |
| Python / package manager | Python 3.14.6; uv locked environment (repository requires >=3.14) |
| Backend | FastAPI 0.162.0, SQLAlchemy 2.1.6, Alembic 1.20.1, chess 1.11.2, Pydantic 2.14.1, Ollama SDK 0.6.3 |
| Frontend | Node 24.19.0, pnpm 12.15.0, Svelte 5.57.2, SvelteKit 3.1.0, Vite 8.3.5, TypeScript 6.0.3, Playwright 1.64.1 |
| Stockfish | Stockfish 19, `/opt/homebrew/bin/stockfish` |
| Ollama | Service/client 0.40.15; installed `qwen3.5:4b-q4_K_M`, Q4_K_M, 3.3 GB |
| Model digest | `d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04` |
| Disk | 297 GiB available at baseline |
| Personal database | Configured default `data/chess_coach.db`; 646 games; never migrated or fault-injected |
| Backup | `/tmp/chess-coach-phase24/backups/chess-coach-20261110-095002Z-el62eaik.db`; SQLite backup API, integrity_check=ok |
| Audit database | `/tmp/chess-coach-phase24/audit.db`, migrated from empty; pytest databases use separate temporary directories |

After execution, read-only hashes of every table's ordered logical contents matched
the verified personal backup. No personal PGNs were modified. The fresh-install
copy excluded local `.env`, databases, virtual environments and node_modules.
No commit or push was made. Initial sandbox cache/network restrictions were
resolved through approved escalation; they were not application failures.

## 3. Audit matrix

Every specification check appears once below (128 rows). PASS means the named
procedure/test executed with the expected invariant, except expressly static
checks (architecture, documentation and O-series), where inspection is the
specified procedure. FIXED refers to the reproduced failure and verification in
section 4. Tests use controlled fixtures; passing does not establish universal
correctness on arbitrary unseen games or prose. Initial statuses for file-import
checks distinguish the absent user entry point from existing Chess.com support.
No changes were required for PASS rows unless the Fix column says otherwise.

For each row, the Requirement states the expected result and Evidence records the
observed result/procedure. The executed command groups and exit codes are in
section 6; root cause, modified files and remaining risk for repairs are in
section 4. Scope limits and unexecuted checks are recorded in sections 7–10.

| ID | Requirement | Initial status | Final status | Evidence / actual result | Fix |
| --- | --- | --- | --- | --- | --- |
| B01 | Identify the repository | PASS | PASS | `pwd`, file inventory, AGENTS/rules/docs read; CLI `chess_coach.cli:main`, FastAPI `api.app:app`, Svelte `src/routes` identified | — |
| B02 | Record Git baseline | PASS | PASS | Clean `git status --short`; branch `chore/phase-23-ci-portfolio`; SHA in section 2 | — |
| B03 | Record environment | PASS | PASS | Version commands, sysctl, df, doctor and actual Stockfish/Ollama calls; section 2 | — |
| B04 | Verify dependency reproducibility | PASS | PASS | `uv sync`; `pnpm install --frozen-lockfile`; fresh locked installs; lockfiles unchanged | — |
| B05 | Establish database safety | PASS | PASS | SQLite backup API + integrity check; all table contents later matched snapshot; 646 games preserved | — |
| B06 | Run baseline tests | PASS | PASS | Baseline: Ruff/mypy 0; pytest 717 passed; frontend checks all exit 0 | — |
| D01 | Verify database migrations | PASS | PASS | `test_migrations_build_empty_database`, `test_alembic_schema_matches_models`; CLI upgrade head also exit 0 | — |
| D02 | Verify incremental synchronization | PASS | PASS | `test_ten_game_archive_then_one_new_game`: 10 → 11; one inserted, ten existing; original rows unchanged | — |
| D03 | Verify duplicate prevention | NOT IMPLEMENTED | FIXED | `test_file_import_identity_source_and_mixed_rejections`: ten repeat imports, no duplicate; database uniqueness tests | F24-01 (file path; Chess.com already passed) |
| D04 | Verify game identity stability | NOT IMPLEMENTED | FIXED | Same test: reordered headers/comments/CRLF deduplicate; different moves stay distinct; file identity v1 documented | F24-01 |
| D05 | Verify original PGN preservation | PASS | PASS | `test_imported_game_is_analyzable_and_source_is_immutable`; raw PGN unchanged after analysis and compatible rerun | — |
| D06 | Verify malformed input isolation | PASS | PASS | `test_mixed_batch_idempotent_and_explicit_retry`, file importer valid/invalid/valid test: two accepted, one preserved rejection | — |
| D07 | Verify tracked-player perspective | PASS | PASS | `test_perspectives`, `test_result_filter_and_rating_use_tracked_player_perspective`: both colors and draws | — |
| D08 | Verify transaction rollback | PASS | PASS | `test_file_import_write_failure_is_atomic`, `test_atomic_transaction_failure_restores_counters`: failure rolls back; retry succeeds | — |
| D09 | Verify archive/network error behavior | PASS | PASS | `test_permanent_errors_and_redirects_never_follow`, `test_retries_bounded`, `test_bad_envelope_not_empty`, empty/conditional archive tests | — |
| D10 | Verify import provenance | NOT IMPLEMENTED | FIXED | File source evidence includes run ID, identity/date/completion provenance; Chess.com source-evidence and import-run tests | F24-01 (file provenance) |
| E01 | Engine availability | PASS | PASS | Real `test_real_engine_contracts`: UCI startup, legal search, shutdown; Stockfish 19 | — |
| E02 | White evaluation orientation | PASS | PASS | Real mirrored-position contracts and `test_normalize`: White-positive canonical scores | — |
| E03 | Black evaluation orientation | PASS | PASS | Same real contracts and mirrored Black mate: Black-negative canonical orientation | — |
| E04 | White move-loss calculation | PASS | PASS | `test_loss`, `test_player_perspective`, pipeline persisted losses | — |
| E05 | Black move-loss calculation | PASS | PASS | Same loss and feature tests for Black; analytics Black-orientation integration | — |
| E06 | Mate-state handling | PASS | PASS | `test_terminal_draw_and_mate`, `test_mate_zero_winner_and_no_cp_conversion`, motif mate transition tests | — |
| E07 | Best-move legality | PASS | PASS | Real engine PV replay + `test_invalid_engine_pv_rejected_without_completion` | — |
| E08 | Engine provenance | PASS | PASS | `test_complete_repeat_cache_and_profile_isolation`; run/config/history persisted and validated | — |
| E09 | Position caching | PASS | PASS | Same pipeline test + imported-game rerun: unchanged engine-call counter | — |
| E10 | Cache invalidation | PASS | PASS | `test_history_and_profile_cache_misses`, `test_recovery_mismatch_preserves_prior_evidence` | — |
| E11 | Resumable engine analysis | PASS | PASS | `test_worker_signal_recovers_ten_games` (SIGKILL/SIGTERM), partial-position resume and commit-preservation tests | — |
| E12 | Engine lifecycle and resource control | PASS | PASS | Real exception/context cleanup, worker cleanup and benchmark exit code; resource limits below | — |
| E13 | Benchmark configuration evidence | FAIL | FAIL | Strict longer benchmark rejected 49/5,760 final-bestmove records; production-adapter sample 192/192 passed | F24-07 |
| A01 | Opening classification | PASS | PASS | `test_phase_fixtures`, `test_phase_progression_and_unknown_setup`: versioned opening heuristic | — |
| A02 | Middlegame classification | PASS | PASS | Same fixture suite includes queenless material semantics; phase is a documented heuristic | — |
| A03 | Endgame classification | PASS | PASS | Rook/pawn and historical endgame fixtures in `test_features.py` | — |
| A04 | White/Black segmentation | PASS | PASS | `test_date_boundaries_filters_and_ties`, `test_color_imbalance_and_confounding_visible` | — |
| A05 | Time-control segmentation | PASS | PASS | `test_partitions_and_unknowns`, `test_request_dates_color_version_and_failed_status` | — |
| A06 | Metric denominators | PASS | PASS | `test_hand_calculated_losses`, `test_context_denominators_overlap_unknowns_and_baseline`, training transfer rate tests | — |
| A07 | Empty-data behavior | PASS | PASS | `test_empty_player_games_and_analytics`, `test_empty_partial_and_low_sample`; no fabricated zero mean | — |
| A08 | Low-sample suppression | PASS | PASS | `test_low_sample_opening_suppressed`, support-boundary tests below/at/above thresholds | — |
| A09 | Historical versus recent windows | PASS | PASS | Cohort window/date-boundary and disjoint recent-trend tests | — |
| A10 | Evidence traceability | PASS | PASS | `test_planted_weakness_end_to_end`, API analytics/evidence consistency; source move links | — |
| A11 | Synthetic known-pattern recovery | PASS | PASS | `test_planted_weakness_end_to_end`, deterministic priority/tie tests | — |
| A12 | Statistical honesty | PASS | PASS | Sample suppression tests, supported-history tests and explicit observational training wording; no general causal inference claimed | — |
| L01 | Local inference verification | PASS | PASS | Loopback model inventory, 50-case real local runs and opt-in API integration; no cloud endpoint | — |
| L02 | Structured output validation | PASS | PASS | 50 first responses per run validated by production schema; malformed-response and bounded retry tests | — |
| L03 | Model provenance | PASS | PASS | Persisted digest/prompt/settings/evidence metadata; evaluation JSON records exact generation settings | — |
| L04 | Deterministic fact immutability | FAIL | FIXED | Existing immutable-field tests plus same-best-move contradiction/abstention regressions | F24-06 |
| L05 | Numerical hallucinations | FAIL | FIXED | New eleven/twenty/thousand/dozen regression failed first; repaired validator and persisted job rejection tests pass (F24-02) | F24-02 |
| L06 | Move hallucinations | FAIL | FIXED | Notation rejected in initial real outputs; stricter prompt evaluated below; fixture illegal-PV and prohibited-move checks pass | F24-03/06 (prompt and same-move guard; semantic review still blocked) |
| L07 | Insufficient-evidence behavior | PASS | PASS | Low-sample historical abstention executes without model; real model abstention rate reported separately below | — |
| L08 | Ollama failure isolation | PASS | PASS | `test_vertical_slice_cache_duplicate_and_offline`, complete browser restart with model offline | — |
| L09 | Prompt-injection boundary | PASS | PASS | `test_prompt_evidence_excludes_imported_prose`; source comments absent from model evidence | — |
| L10 | LLM caching | PASS | PASS | `test_digest_prompt_settings_and_evidence_cache_misses`, `test_prompt_version_change_misses_existing_success` | — |
| L11 | Model evaluation evidence | FAIL | FAIL | Reproducible development runs exist; reviewed factuality and comparative model-selection evidence absent (F24-04/05) | F24-04/05 |
| L12 | Coaching quality | BLOCKED | BLOCKED | No independent assertion labels or coaching-quality rubric scores; cannot substitute model judging for requested review | F24-04 |
| P01 | OpenAPI documentation | PASS | PASS | Fresh server GET /docs and /openapi.json both 200; schema equals checked-in frontend snapshot | — |
| P02 | Explicit request/response schemas | PASS | PASS | Explicit Pydantic response schemas, OpenAPI contract tests; no ORM response objects | — |
| P03 | Pagination | PASS | PASS | `test_pagination_order_detail_and_pending`, invalid pagination parametrization; browser 26-game pagination | — |
| P04 | Long-running jobs | PASS | PASS | `test_analysis_pending_request_completes_and_no_work_avoids_engine`, browser asynchronous completion | — |
| P05 | Duplicate job prevention | PASS | PASS | Same/cross-operation simultaneous submissions yield one accepted run and conflict | — |
| P06 | Stable error responses | PASS | PASS | API invalid, missing-resource, unavailable-worker/model, conflict and pagination tests | — |
| P07 | No stack-trace exposure | PASS | PASS | `test_security_errors_and_unexpected_exception`, safe correlated diagnostics tests | — |
| P08 | Local network exposure | PASS | PASS | Loopback CLI/launchers; Host/Origin safeguards; cross-site request regression tests | — |
| P09 | Contract consistency | PASS | PASS | Actual OpenAPI equals frontend JSON; generated-client types pass check; real fixture HTTP workflow | — |
| U01 | Central API client | PASS | PASS | Production fetch only in `frontend/src/lib/api/client.ts`; client error/timeout unit tests | — |
| U02 | Type safety | PASS | PASS | Svelte check: zero errors/warnings; no production TypeScript any found | — |
| U03 | Loading state | PASS | PASS | Delayed games loading and workflow progress browser assertions | — |
| U04 | Empty state | PASS | PASS | Dashboard/games empty-state browser tests plus empty API fixtures | — |
| U05 | Backend error state | PASS | PASS | Games retry, dashboard section failure, health disconnect/reconnect browser tests | — |
| U06 | Successful workflows | PASS | PASS | `e2e/complete-workflow.spec.ts`: full real HTTP/persistence flow with explicitly fake external adapters | — |
| U07 | No duplicate submissions | PASS | PASS | Sync duplicate-click tests, competing analysis admission, idempotent training retry and concurrent attempt tests | — |
| U08 | No authoritative chess logic in Svelte | PASS | PASS | Board rendering helpers inspected; authoritative legal moves/loss/ranking provided by FastAPI | — |
| U09 | Basic accessibility | PASS | PASS | Keyboard/skip-link/narrow viewport navigation test; semantic labeled controls inspected; not a full accessibility certification | — |
| T01 | Historical error to puzzle | PASS | PASS | Generation/reconstruction tests reject corrupt source FEN/ply/history; browser generated puzzle uses saved mistake | — |
| T02 | Puzzle ambiguity | PASS | PASS | `test_mate_compared_separately_and_second_mate_is_ambiguous`, gap/rank tests, real MultiPV contract | — |
| T03 | Puzzle solution legality | PASS | PASS | Real MultiPV legal replay, corrupt evidence rejections, stored solution validation before attempt commit | — |
| T04 | Attempt persistence | PASS | PASS | `test_wrong_answer_retry_restart_and_statistics`, browser committed submission after restart | — |
| T05 | Review scheduling | PASS | PASS | `test_review_intervals`, frozen UTC dates, wrong and consecutive correct intervals | — |
| T06 | Prevent answer leakage | PASS | PASS | PublicPuzzle excludes solution; browser grade/solution appears after submission; no visible pre-answer leak | — |
| T07 | Improvement measurement | PASS | PASS | `test_transfer_keeps_comparable_periods_and_drops_incomplete_analysis`, threshold/rate tests; noncausal UI wording | — |
| R01 | Chess.com network failure | PASS | PASS | Durable timeout retry and existing-source preservation tests | — |
| R02 | Chess.com rate limiting | PASS | PASS | Bounded retry-after/exhaustion tests; browser actionable rate-limit recovery | — |
| R03 | Stockfish unavailable | PASS | PASS | Missing engine does not block stored browsing; admission unavailable tests and real launcher with absent engine | — |
| R04 | Ollama unavailable | PASS | PASS | Model-offline fixtures retain engine evidence/analytics and saved coaching | — |
| R05 | Interrupted analysis | PASS | PASS | SIGKILL/SIGTERM production worker subprocess recovery tests | — |
| R06 | Concurrent operations | PASS | PASS | Concurrent same/cross-job requests, single-worker guard, concurrent snapshot read tests | — |
| R07 | SQLite locking | PASS | PASS | New real SQLite write-contention test: 50 ms busy timeout, safe failed transaction, retry after lock release | — |
| R08 | Storage failures | PASS | PASS | Rollback/finalization/storage failure tests, worker low-disk preflight, read-only/unusable directory diagnostics | — |
| R09 | Backend restart | PASS | PASS | Complete workflow API restart and persisted source/run/coaching/attempt tests | — |
| R10 | Frontend/backend reconnection | PASS | PASS | Browser disconnect/retry and complete-workflow restart | — |
| R11 | Post-game safety boundary | PASS | PASS | No arbitrary-position product endpoint; malformed/unfinished/variant import and source-completion checks | — |
| H01 | Process liveness | PASS | PASS | Fresh /health and /health/ready; liveness tests explicitly forbid optional probes | — |
| H02 | Dependency status | PASS | PASS | Independent component status tests; doctor reports SQLite, engine, service and model; worker status tracked separately | — |
| H03 | Database health | PASS | PASS | Fresh migrated DB integrity/foreign keys; read-only and incompatible-schema tests; personal snapshot verified | — |
| H04 | Stockfish health | PASS | PASS | Actual engine contracts execute search; health probe UCI handshake and timeout cleanup tested | — |
| H05 | Ollama health | PASS | PASS | Actual inventory and inference; fixtures distinguish missing service/model; generation bounded to 90 s | — |
| H06 | Background worker health | PASS | PASS | Heartbeat and stale-worker state/recovery tests; no falsely completed interrupted games | — |
| H07 | Resource health | PASS | PASS | Bounded engine batch, process sample and before/after memory pressure below; no thermal optimality claim | — |
| H08 | Startup diagnostics | PASS | PASS | `doctor --deep` exit 0 on audit DB, every check PASS; invalid settings/paths tested separately | — |
| H09 | Health-state breakdown table | PASS | PASS | Failure table exercised by R01–R11 and health tests; frontend failure does not delete backend data | — |
| Q01 | Ruff | PASS | PASS | `uv run ruff check .`: exit 0 | — |
| Q02 | mypy | PASS | PASS | `uv run mypy src`: exit 0, 109 source files | — |
| Q03 | pytest | PASS | PASS | Full pytest: 735 passed, 7 explicit opt-in skips, 3 engine deselections; opt-ins separately executed below | — |
| Q04 | Coverage | PASS | PASS | Line coverage 5635/6252 (90.13%); expanded deterministic core 1899/2020 (94.01%) | — |
| Q05 | Svelte type checking | PASS | PASS | `pnpm check`: exit 0, zero errors/warnings | — |
| Q06 | Vitest | PASS | PASS | `pnpm test`: exit 0, 37 tests / 8 files | — |
| Q07 | Frontend production build | PASS | PASS | `pnpm build`: exit 0; also fresh-install and Playwright build | — |
| Q08 | Playwright | PASS | PASS | `pnpm test:e2e`: 40 passed, 3 explicit legacy opt-ins skipped | — |
| Q09 | CI | BLOCKED | BLOCKED | Workflow inspected and local commands executed; no gh executable/connected GitHub; public Actions API inaccessible | Remote CI access |
| Q10 | Reproducible fresh installation | PASS | PASS | Fresh tracked-source copy with no personal .env/data/dependencies: locked installs, migration, build, launcher and five HTTP URLs all pass | — |
| Q11 | Architecture boundaries | PASS | PASS | Domain imports checked for forbidden dependencies; central API access and thin routes inspected; no new SQL in routes | — |
| F01 | Architecture diagram | PASS | PASS | `docs/architecture.md` diagram compared to real API/workers/repositories and complete workflow | — |
| F02 | Evaluation report | FAIL | FAIL | This report records reproducible development evaluation and limits; reviewed release-quality report remains missing | F24-04 |
| F03 | Model-selection report | NOT IMPLEMENTED | NOT IMPLEMENTED | `docs/evaluation/model-selection.md` explicitly has no reviewed multi-model comparison; only installed 4B model tested | F24-05 |
| F04 | M5 Air benchmark | PASS | PASS | Exact machine/profile, actual searches and LLM latencies recorded below; historical benchmark claims explicitly scoped | — |
| F05 | Architectural decision records | PASS | PASS | `docs/adr/README.md`: seven decisions include context/options/tradeoffs/revisit triggers | — |
| F06 | Demonstration | PASS | PASS | Documented fixture demo command is the same complete-workflow test executed successfully; existing capture is labeled synthetic | — |
| F07 | README | FAIL | FIXED | README/setup/operations/testing/evaluation/limitations links inspected; file-import command and identity documentation added | F24-01 docs |
| F08 | Limitations and honesty | PASS | PASS | Experimental motifs withheld; deterministic facts separate; limitations explicit; no unsupported quality/optimality claims introduced | — |
| F09 | Reproducibility without personal data | PASS | PASS | Offline complete workflow and fresh install executed without personal data; synthetic fixtures checked in | — |
| O01 | No infrastructure for hypothetical scale | PASS | PASS | Final diff, dependency manifests and architecture inspected; no added dependency | — |
| O02 | No unnecessary frameworks | PASS | PASS | Final diff, dependency manifests and architecture inspected; no added dependency | — |
| O03 | No speculative abstractions | PASS | PASS | Final diff, dependency manifests and architecture inspected; no added dependency | — |
| O04 | No unnecessary database redesign | PASS | PASS | Final diff, dependency manifests and architecture inspected; no added dependency | — |
| O05 | No model training | PASS | PASS | Final diff, dependency manifests and architecture inspected; no added dependency | — |
| O06 | No vector database by default | PASS | PASS | Final diff, dependency manifests and architecture inspected; no added dependency | — |
| O07 | No UI beautification project | PASS | PASS | Final diff, dependency manifests and architecture inspected; no added dependency | — |
| O08 | No fake observability complexity | PASS | PASS | Final diff, dependency manifests and architecture inspected; no added dependency | — |
| O09 | No broad dependency upgrades | PASS | PASS | Final diff, dependency manifests and architecture inspected; no added dependency | — |
| O10 | No endless rewriting | PASS | PASS | Final diff, dependency manifests and architecture inspected; no added dependency | — |

## 4. Defects found and repairs

### F24-01 — P2: no user-facing PGN file import

- **Before:** `uv run chess-coach import-pgn --help` exited 2 (unknown command).
  The parser and storage accepted fixture-created PGN records, but no public file
  import existed. Identity normalization was still described as planned.
- **Cause:** missing application entry point and file identity/persistence path.
- **Repair:** added `import-pgn`, bounded to 100 single-game UTF-8 files with an
  explicit historical timezone-aware timestamp. It reuses strict legal/completion
  validation, preserves raw source including CRLF, records rejected games and
  provenance, serializes admission, and commits the batch atomically.
  SQLite's existing unique canonical hash enforces identity. No migration needed.
- **Files:** `src/chess_coach/application/import_pgn.py`,
  `src/chess_coach/infrastructure/persistence/pgn_repository.py`,
  `src/chess_coach/cli.py`, `tests/integration/persistence/test_pgn_import.py`,
  `README.md`, `docs/PERSISTENCE.md`.
- **Verification:** new public CLI test failed before implementation; 12 import
  tests then passed, including ten duplicate imports, formatting normalization,
  distinct moves, malformed/unfinished/multigame rejection, source preservation
  through analysis, zero-search compatible rerun, storage rollback/retry and
  invalid path/encoding/size/date/player/conflicting-job safeguards.
- **Residual scope:** CLI only; one game per file. No browser file-upload control
  or automatic Chess.com/file cross-source merge. Explicit date is user-supplied
  provenance, not inferred truth. Identical metadata and moves cannot distinguish
  two real encounters; use their actual timestamps. Time class is left unknown.

### F24-02 — P1: spelled-out numeric hallucinations accepted

- **Before:** the regression in `test_output_and_detectable_claims` failed:
  unsupported “eleven mistakes” passed validation. “twenty games”, “a thousand
  points” and “a dozen times” exposed the same hole.
- **Cause:** the numeric-claim filter listed zero through ten but omitted other
  common English number words.
- **Repair:** extended the prohibited numeric vocabulary without allowing the LLM
  to calculate or supply trusted numeric fields. Existing cached responses are
  revalidated through the same production validation path.
- **Files:** `infrastructure/llm/validation.py`,
  `tests/unit/coaching/test_coaching_contracts.py`,
  `tests/api/test_coaching_routes.py` (source paths under `src/chess_coach/`).
- **Verification:** regression failed before repair; unit checks pass afterward;
  parameterized API test verifies unsupported counts produce failed coaching jobs,
  followed by successful retry/cache repair. Deterministic evidence stays intact.
- **Residual risk:** vocabulary filters do not prove arbitrary natural-language
  factuality. Novel phrases and nonnumeric unsupported claims still need review.

### F24-03 — P2: model repeatedly violated prose restrictions

- **Before:** actual 50-case local evaluation produced 50 schema-valid responses
  but only 4 accepted by production grounding validation. Rejected examples copied
  move identifiers into summaries despite prompt restrictions.
- **Cause:** insufficiently explicit output wording examples for this model.
- **Repair:** prompt `coaching-v1.2` explicitly forbids copying identifiers/numbers
  into any prose field, including abstentions, and provides balanced examples of
  abstention and a limited engine-evaluation comparison. Prompt-version identity
  invalidates incompatible generation caches. Validator rules were not relaxed.
- **Files:** `src/chess_coach/infrastructure/llm/prompts.py`; evaluation artifacts
  listed below. Prompt/cache compatibility already has automated regression tests.
- **Verification:** a first prompt revision reached 50/50 automated acceptance but
  abstained on all cases. That was treated as a failed usefulness experiment.
  The final balanced revision's measured results are in section 9.
- **Residual risk:** development-set tuning is not held-out evaluation. Accepted
  generic explanations and abstentions are not evidence of helpful coaching.

### F24-04 — P2: release-quality coaching evidence missing

- **Before/after:** FAIL for release evidence; BLOCKED for independent human scoring.
- **Evidence:** development corpus has unreviewed expected-status fields; zero human
  assertion labels/rubric reviews in the run artifacts. Existing evaluation docs
  acknowledge this. Neither this audit nor automated validation replaces that work.
- **Required work:** curate and freeze representative mistake/abstention examples,
  collect independent assertion-level labels and rubric scores, adjudicate them,
  and report errors, unsupported assertions and abstentions with denominators.
  The repository's future targets require at least 200 held-out cases.
- **No unsafe substitute:** no invented quality percentages or fabricated labels.

### F24-05 — P2: comparative model selection not implemented

- **Before/after:** NOT IMPLEMENTED. Only the installed 4B Q4_K_M model was evaluated.
- **Evidence:** `docs/evaluation/model-selection.md` explicitly defers reviewed
  multi-model comparison; current selection is a development choice.
- **Required work:** compare candidate local model/digest/quantization settings on
  the same reviewed dataset with quality, first-response acceptance, abstention,
  latency and resource measurements. Record rationale and tradeoffs.
- **Scope:** installing arbitrary models and scoring unlabeled text would not close
  the quality gap. The current model remains local and optional.

### F24-06 — P1: an engine-matching move described as a mistake

- **Before:** 15 real-model outputs claimed a preferred alternative although
  `played_move_uci == best_move_uci`. They passed the previous checks. A new
  same-best-move regression reproduced the failure.
- **Cause:** the prompt required abstention but application validation did not
  enforce this deterministic relationship.
- **Repair:** reject explained output for identical played/best moves. Product
  GET/POST now return an explicit deterministic abstention before model or cache
  access for this case, preserving authoritative evidence and avoiding wasted work.
- **Files:** `src/chess_coach/application/coaching.py`,
  `src/chess_coach/infrastructure/llm/validation.py`,
  `tests/unit/coaching/test_coaching_contracts.py`.
- **Verification:** failing regression then passing same-move rejection/abstention
  tests, with no health/model/store calls. All 50 saved outputs revalidated:
  the 15 known contradictions are rejected; 35 pass the final automated checks.
- **Residual risk:** general semantic factuality is still not proven. Numerical
  loss can disagree with an identical best move because searches are independent;
  the new behavior conservatively abstains instead of inventing another move.

### F24-07 — P2: strict final-bestmove benchmark has rejected searches

- **Before/after:** FAIL; 49/5,760 searches at the default node/thread/hash profile
  lack an unbounded evaluation paired with the final UCI bestmove.
- **Cause:** bounded multi-threaded searches can finish with a final move whose
  exact score/PV was not emitted. The benchmark deliberately rejects this.
- **Investigation:** all failures had the same diagnostic. The application uses
  the documented latest-complete-unbounded-update policy; a separate 192-position
  production-adapter sample passed. Engine exit and process cleanup succeeded.
- **Disposition:** retained the strict benchmark, recorded the result, and did not
  replace exact scores with bounds or claim an optimal configuration. No production
  fix is justified by this measurement alone; controlled profile comparison is
  required before a clean performance-readiness claim.

## 5. Changes made

| Area | Changes |
| --- | --- |
| Backend/application | Bounded file import service and CLI command |
| Database | New import repository using existing tables/constraints; no migration or real-data change |
| Analytics | No production changes; added exact incremental-sync and SQLite contention verification |
| LLM | Broader numeric-claim veto, versioned prompt examples and deterministic same-best-move abstention |
| API | No route/schema change; added persisted-failure/retry regression coverage |
| Frontend | No source or generated-contract change |
| Tests | New file-import suite; ten-to-eleven sync, write contention and spelled-number regressions |
| Documentation | README import instructions, explicit identity/limits in PERSISTENCE, this consolidated report |

No dependency, distributed infrastructure, new framework, speculative worker,
model-training, vector database or visual redesign was introduced. Existing
unrelated code was preserved. Test helper formatting was limited to touched files.

## 6. Automated test results

Raw session logs are under `/tmp/chess-coach-phase24/`; these are local artifacts,
not required inputs for reproducing the tests. Counts below are observed, not
inferred from prior phase reports.

| Command | Observed result | Exit |
| --- | --- | --- |
| `uv sync` | Existing environment resolved; 48 packages resolved, 47 checked | 0 |
| `pnpm install --frozen-lockfile` (frontend) | Locked dependencies installed; constraints/lockfiles unchanged | 0 |
| `uv run ruff check .` | Baseline and repaired tree pass | 0 |
| `uv run mypy src` | Repaired tree: 109 source files, no issues | 0 |
| `uv run pytest --cov=chess_coach --cov-report=term-missing --cov-report=json:... --junitxml=...` | Baseline 717 passed; repaired tree 735 passed, 7 skipped, 3 deselected | 0 |
| `uv run pytest -m engine tests/integration/test_stockfish_real.py` | 3 real Stockfish tests passed | 0 |
| `CHESS_COACH_TEST_LAUNCHERS=1 uv run pytest tests/integration/test_local_launchers.py` | 7 passed using isolated storage and actual launchers | 0 |
| `pnpm lint` | Prettier and ESLint pass | 0 |
| `pnpm check` | Zero Svelte/TypeScript errors or warnings | 0 |
| `pnpm test` | 37 passed, 8 files | 0 |
| `pnpm build` | Static production build emitted | 0 |
| `pnpm test:e2e` | 40 passed, 3 legacy opt-in skips | 0 |
| Fresh-copy `uv sync --locked`, frozen pnpm install, Alembic upgrade, build | All succeeded without personal data or pre-existing environment | 0 each |
| Fresh-copy `./scripts/start.sh` | `/`, `/docs`, `/openapi.json`, `/health`, `/health/ready` all HTTP 200; owned process terminated afterward | 0 verification |
| `doctor --deep` against audit DB | All checks PASS, overall HEALTHY | 0 |
| Actual OpenAPI vs frontend snapshot | JSON equality true | 0 verification |

Coverage: **5,635 / 6,252 executable backend lines = 90.13%**.
Expanded deterministic core: **1,899 / 2,020 lines = 94.01%**. This core includes
all production modules in `chess_coach.analytics` and `chess_coach.domain`, plus
`infrastructure.pgn.parser`, `application.analysis`, `analysis_worker` and
`infrastructure.persistence.analysis_repository`. The prior phase's narrower
core is also 1,402 / 1,495 = 93.78%. These are line rates, not branch rates.
No production exclusions were added. Coverage does not establish model quality.

The seven normal pytest skips are six opt-in launcher cases and the opt-in real
Ollama test; launchers were executed separately. Three deselections are real
Stockfish tests, also executed separately. Browser skips require the legacy real
analysis/recovery/training environments; the complete offline boundary-crossing
workflow ran. Existing python-chess Python 3.16 deprecation warnings and the
Vitest/Svelte transformIndexHtml warning did not fail checks.

Remote CI remains **BLOCKED**: no `gh` executable/connected GitHub tool was
available, and the public Actions API URL was inaccessible through the web tool.
The workflow YAML and locally reproducible commands were checked; this report
makes no claim that hosted CI is green.

## 7. Reliability tests

All faults were confined to disposable databases/processes. The matrix references
executed test names. The following outcomes were observed:

- Timeout, rate limiting, upstream HTTP/schema errors: bounded retries or safe
  failure; prior games and committed archive checkpoints survive.
- Invalid PGN: rejected text retained; valid neighboring inputs remain usable.
- Duplicate/simultaneous requests: one durable job/attempt; conflicts or idempotent
  retries; no duplicate state. Ten-game incremental fixture gains exactly one row.
- SIGKILL/SIGTERM during production analysis: restart resumes the same durable run;
  committed results survive and incompatible profiles are not silently reused.
- SQLite contention: actual write reservation blocks a second writer; bounded
  failure leaves no import run; releasing the lock permits retry.
- Failed commits/storage access/low-disk preflight: no falsely completed analysis
  or partially committed attempts; source and existing evidence remain intact.
- Missing Stockfish: saved views stay available; new analysis reports unavailable.
- Missing Ollama: deterministic data and cached coaching remain available;
  independent failed coaching can retry.
- Backend disconnect/restart: browser recovers and reads persisted reports and
  training attempts. Browser closure does not cancel accepted background work.

Not executed: destructive tests on real data, physically filling the disk,
thermal endurance over hours, human quality annotation, additional local-model
comparison, and remote CI defect-injection PRs. These are not claimed as PASS.
The existing demo recording was not regenerated; its reproducible fixture
workflow was executed successfully.

## 8. Health and safety

The API/launchers bind to loopback; Host and Origin checks reject cross-site
mutations. Core readiness reports actual storage/schema failures separately from
process liveness and optional model outages. Diagnostic failures are sanitized.
Stockfish probes perform a UCI handshake; the independent real-engine tests and
benchmark perform actual legal searches. Ollama service and model availability
are separate diagnostics, followed here by actual bounded inference.

Completed source evidence and legal replay gate analysis. File imports trust an
explicit terminal PGN declaration and disclose that provenance. There is no
arbitrary-position/live-game recommendation endpoint. Training uses saved
completed-game mistakes. Engine evaluations and numeric analytics remain separate
from model-authored prose. No real-game network import was needed for this audit.

Verified backup and exact logical-table comparison protect the personal library.
No schema change was made. Benchmark data stays under the harness's ignored
`data/benchmarks/` directory; synthetic model evaluation outputs contain no personal
PGNs. Audit-created servers are stopped after checks; engine cleanup is tested.

## 9. Performance and model measurements

These are measurements on this M5/16 GiB machine, on battery power, not claims
of optimal settings or controlled thermal performance. Stockfish and model work
partly overlapped during the longer runs; latency comparisons are confounded by
that contention. No production configuration was silently changed to improve a score.

### Engine

The frozen `m5-benchmark-v1` calibration dataset preserves legal move histories.
Positions SHA-256 is
`eddc39b847280aba592b43a5438a4a36d3ee9ddf8e64d275b653f0b3240e72ce`.
The harness resets UCI game state per search, records final node telemetry, and
requires an unbounded score/PV corresponding to the final UCI best move.
Settings: **Threads=4, Hash=512 MiB, 10,000 nodes, MultiPV=1**.

| Run | Observed result | Search wall / total batch |
| --- | --- | --- |
| Ten positions × three repetitions | 30/30 succeeded; exit 0 | 0.421 / 0.752 seconds |
| 192 calibration positions × 30 repetitions | 5,711 succeeded; 49 safely rejected; exit 1 | 86.504 / 88.470 seconds |
| Production adapter on all 192 calibration positions | 192/192 succeeded, no exceptions | 2.608 seconds including adapter lifecycle |

All 49 benchmark rejections were `No unbounded score and PV matching final UCI
bestmove` (0.85% of 5,760 searches). This is not an illegal-move or data-corruption
result. The benchmark correctly refuses an unevidenced final move. The production
adapter intentionally uses the latest complete, unbounded score/PV update from
one iteration, documented in README, rather than combining a final move with a
mismatching score. Its separate sample passed. No safety assertion was weakened
and no default budget changed based on this one experiment. A clean comparative
final-bestmove benchmark remains outstanding (F24-07).

The longer batch completed in about 88 seconds and the engine exited 0. A process
sample during work showed one Stockfish at 348.2% CPU and 893,360 KiB RSS. Memory
pressure moved from level 1 to level 2; swap was 2,059.44 MiB before and immediately
after. A later cleanup check found level 1, no Stockfish process, and no loaded
Ollama model; swap then measured 2,530.75 MiB. Other desktop activity and overlapping
inference prevent attributing system-wide changes solely to Stockfish. This is a
bounded-load observation, not hours-long endurance or a recommendation for concurrent
engine/model operation. The production combined worker releases Stockfish before
coaching, which is independently tested.

Raw private benchmark results remain in ignored
`data/benchmarks/results/phase24-audit/` and `phase24-sustained/`. Reproduce using a
new output directory (the harness deliberately refuses overwriting a run):

```sh
uv run python -m benchmarks.benchmark_stockfish \
  --dataset data/benchmarks/datasets/m5-v1 \
  --output data/benchmarks/results/phase24-repeat \
  --threads 4 --hash-mb 512 --nodes 10000 --limit 192 --repetitions 30
```

That historical benchmark corpus is local/private. The repository's unit, engine,
fresh-install and complete-product demo checks use checked-in synthetic fixtures
and do not require it. Follow `docs/benchmarks/m5-air.md` to prepare a new eligible
corpus; different input hashes are not the same experiment.

### Local model

Dataset: `evaluation/datasets/move_explanations_v1.jsonl`, 50 synthetic development
cases; hash `c3b94dffc4a150483a3dd66d7e977f40305a55f1c453b41f06b00df5366c68fa`.
All calls used the same installed model/digest from section 2, temperature 0,
context 4,096, output cap 800, thinking false, keep_alive 0 and timeout 90 seconds.
Each evaluation counted first responses; there were no retries counted as successes.

| Experiment | Schema valid | Accepted by applicable checks | Accepted explained / abstained | Median latency |
| --- | --- | --- | --- | --- |
| Original prompt v1.1 | 50/50 | 4/50 under then-current checks | See raw initial outputs; most failures copied move notation | 3,316 ms |
| First wording revision (rejected experiment) | 50/50 | 50/50 under then-current checks | 0 / 50 | 2,521.5 ms |
| Balanced prompt v1.2, then final deterministic revalidation | 50/50 | 35/50 | 21 / 14; 15 contradictory explanations rejected | 5,174.5 ms |

The last run originally passed 50/50 under the old validator. Inspecting the
actual content revealed 15 explanations inventing an alternative when the played
move already equaled best. The new same-move guard rejects those saved outputs.
Normal product requests now abstain deterministically **before** model/cache access
for this situation. The evaluation deliberately calls the model on every case,
so its 35/50 count must not be relabeled as 50 successful model responses.
No fresh inference was claimed for the deterministic revalidation.

Saved reproducible evidence:

- [Initial model run](../../evaluation/results/phase24-initial.json).
- [Final model run and post-audit validation](../../evaluation/results/phase24-final.json).
- `CHESS_COACH_REAL_OLLAMA=1 uv run pytest tests/api/test_coaching_routes.py -k real_ollama`
  also ran: **1 passed, 21 deselected, exit 0** at that stage.

```sh
uv run python -m chess_coach.evaluation.move_coaching \
  --output /tmp/phase24-new-model-run.json
```

This was prompt development on reused examples. It is **not held-out quality
measurement**, independent human review, a comparative model benchmark, or proof
that explanations are educationally useful. Human-reviewed examples remain zero.
The more restrictive validator and deterministic abstention protect the observed
failure modes; unrestricted prose semantics remain an explicitly unverified risk.

## 10. Remaining issues and acceptance gates

### Must fix before use

No unresolved reproduced P0/P1 remains in the tested boundaries. Use the product
for completed-game deterministic review; treat generated prose as experimental.
This statement is bounded by the fixtures and checks above, not a universal safety
guarantee or an endorsement of unreviewed model claims.

### Must complete before a portfolio-ready claim

1. **P2 — F24-04:** create reviewed representative/held-out evidence and publish
   assertion-level factuality, abstention and coaching-quality results. Do not
   count zero assertions or generic abstention as quality success.
2. **P2 — F24-05:** compare appropriate local models on that same dataset and
   record digests/quantization, quality, latency, memory and selection tradeoffs.
3. **P2 — F24-07:** resolve the default-budget final-bestmove benchmark rejection
   rate through controlled profile comparisons; preserve the benchmark's strict
   evidence policy. Repeat without overlapping inference, on a documented power/
   thermal setup. Do not call the current configuration optimal.
4. **BLOCKED — Q09:** obtain authenticated hosted Actions results for the reviewed
   commit and required branch checks. Local green checks are not remote CI evidence.

### Optional future improvements

- Browser PGN upload and multi-game file splitting, if desired; the implemented
  CLI already supports bounded completed-game file imports.
- Longer sustained-resource experiments and additional deterministic fixtures.
- Replace deprecated upstream python-chess asyncio APIs when a verified compatible
  release exists; no speculative dependency upgrades were made here.

| Final gate | Status | Evidence / remaining condition |
| --- | --- | --- |
| 1 — Data integrity | PASS | Migrated fixture databases, identity/rejection/rollback/source-preservation and recovery tests |
| 2 — Chess correctness | PASS | Both-color scoring, mate/PV/history/cache tests and real engine adapter checks; strict benchmark rejection reported separately |
| 3 — AI grounding | BLOCKED | Observed factuality holes repaired; reviewed semantic/quality metrics and model comparison still missing |
| 4 — End-to-end product | PASS | Controlled browser workflow with real application boundaries and fixture external adapters; real engine/model tested separately |
| 5 — Engineering reproducibility | BLOCKED | Local fresh installation/checks pass; hosted CI and clean comparative performance/quality evidence outstanding |

## 11. Final recommendation

**CONDITIONAL — Usable, not fully portfolio-ready.**

The audit executed the application and its checks, repaired the missing PGN file
entry point and observed grounding defects, preserved the real library, and
recorded failures rather than hiding them. Finish the reviewed quality dataset,
model comparison, controlled benchmark follow-up and hosted CI verification before
claiming all five portfolio gates pass. No commits or pushes were performed.
