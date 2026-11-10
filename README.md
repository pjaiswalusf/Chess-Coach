# Chess Coach

Chess Coach helps you review completed games and find recurring mistakes
across your own history. Import a Chess.com archive, analyze games with
Stockfish, then trace a pattern back to a specific position. Turn selected
mistakes into one-move puzzles for spaced review.

Stockfish supplies evaluations and candidate moves. Python checks legality,
calculates loss and aggregates historical evidence. Optional Ollama
explanations use those saved facts. The game library and inference stay on
your machine. Chess.com sync reads public historical archives.

## Run locally on macOS

Use Python 3.14, uv, Node 24, pnpm 12.15.0 and Stockfish. Follow the
[setup guide](docs/SETUP.md) to install locked dependencies, migrate SQLite,
build the interface and start the API and workers. The packaged app serves
the UI and API on port 8000.

- [Architecture and failure boundaries](docs/architecture.md)
- [Testing and CI](docs/TESTING.md)
- [Model evaluation](docs/EVALUATION.md)
- [M5 benchmarks](docs/BENCHMARKS.md)
- [Operations and troubleshooting](docs/operations.md)
- [Limitations](docs/LIMITATIONS.md)
- [Synthetic demonstration](docs/demo/README.md)

Development rules and completion checks live in [AGENTS.md](AGENTS.md).

## Interfaces reserved for future features

`application/ports.py` and `domain/models.py` are retained as draft contracts.
They have no current runtime consumers. Before implementing them, review game
identity, full position history, cache compatibility, draw policy, and structured
coaching evidence against the shared rules. In particular, a FEN-only signature
is not sufficient for history-sensitive analysis.

### Completed Chess.com game imports

```sh
uv run alembic upgrade head
uv run chess-coach sync --username YOUR_NAME --dry-run
uv run chess-coach sync --username YOUR_NAME
uv run chess-coach sync-status --username YOUR_NAME
```

Use `--month YYYY/MM` for a small first import or `--force` for a deliberate
historical rescan. See [Phase 7 synchronization](docs/phase-7-sync.md) for recovery,
identity, validation scope and verified results. Full PGN legal replay is Phase 8.

### Stockfish adapter (Phase 9)

Run `uv run chess-coach doctor` to check configuration, SQLite, migrations,
Stockfish, and the local Ollama model. Add `--deep` for a read-only SQLite
integrity and foreign-key check. The System page shows component health and
recent run metrics. See [Diagnostics and observability](docs/observability.md).

Run `uv run chess-coach engine-check` for a fixed-position startup, ping, legal-PV,
analysis, and shutdown check. Install Stockfish separately; the command never
installs or upgrades it. Run real-engine contracts explicitly with
`uv run pytest -m engine`; ordinary `uv run pytest` excludes them.

The internal `StockfishAdapter` is for offline analysis of completed games;
there is no arbitrary-position HTTP endpoint. Use it as a context manager and
pass a stable `game` identifier for consecutive positions in the same game.
Commands on one adapter serialize; callers must share one adapter per batch.
Failures discard the process and require explicit `start()` before retrying;
there are no automatic retries. Optional depth/nodes fields reflect engine
reports, never invented measurements.

Configuration uses `CHESS_COACH_STOCKFISH_` plus `EXECUTABLE`, `THREADS` (4),
`HASH_MB` (512), `NODES` (10000), `MAX_NODES` (10000000), `SEARCH_SECONDS` (3),
and `TIMEOUT_SECONDS` (10). Search uses both nodes and finite time, with protocol
operation timeout in addition. These defaults are not throughput benchmarks.

Scores are White-centric; mate remains separate from centipawns. `mate_winner`
retains the winner when distance is zero. CP loss accepts only CP integers and
is a provisional estimate from independent searches, clamped at zero.
Draw policy `automatic-only-v1`: checkmate, stalemate, insufficient material,
fivefold repetition, and the 75-move rule terminate analysis; claimable threefold
and 50-move draws are not assumed claimed. Terminal results have no PV and do
not run a search. Full supplied move history is validated and forwarded;
pre-FEN history remains unknown. Phase 10 adds compatible history-aware caching; incompatible histories are never reused.

Engine evidence uses the latest complete, unbounded UCI score/PV update.
Depth and nodes describe that update, rather than a later partial search update.
This avoids stale bound flags in python-chess's aggregated information; a search
with only bounded scores fails explicitly. The standard python-chess UCI parser,
process management, and finite `SimpleEngine.analyse` timeout remain in use.


### Persistent analysis (Phase 10)

Start `uv run chess-coach analysis-worker` alongside the API and frontend, then
select **Analyze eligible games**. Completed work survives browser closure and
worker interruption. Retry, cancellation, progress, and per-move evidence are
available in the UI. The worker uses one configured analysis budget; losses are
search estimates, not confirmed mistake classifications.

See the [operations runbook](docs/operations/analysis-runbook.md),
[validation record](docs/PHASE10_VALIDATION.md), and
[measured baseline](docs/benchmarks/phase10-baseline.md).

### Deterministic features (Phase 11)

After `uv run alembic upgrade head`, extract features offline from a stored analysis
profile with `uv run chess-coach extract-features --username YOUR_USERNAME --profile PROFILE_HASH`.
Use `--profile board-only` for board and clock facts without engine evidence.
The command resumes by skipping complete matching snapshots and never starts an
engine or model. See the [feature contract and recovery instructions](docs/FEATURES.md)
and [validation record](docs/PHASE11_VALIDATION.md).


### Longitudinal analytics (Phase 12)

Run `uv run chess-coach analytics-health --player-id PLAYER_ID --profile PROFILE_HASH --window last_100`
for a read-only JSON report of cohort health, outcomes, segmented errors, contextual
opportunities, advantage conversion and supported category-specific weaknesses.
This needs stored analysis, starts no engine/model/server, and preserves pending
games in the selected window. See [analytics semantics and usage](docs/ANALYTICS.md),
[troubleshooting](docs/analytics-troubleshooting.md) and
[validation and performance limits](docs/PHASE12_VALIDATION.md).


### HTTP contracts (Phase 13)

The [API contract](docs/api-contract.md) documents player configuration, bounded
historical game queries, stored analysis, persistent sync/analysis jobs, analytics,
local safeguards, and error schemas. Generated OpenAPI is at `/openapi.json`.
Start `uv run chess-coach sync-worker` to process durable sync requests and validate
imported PGNs. Start the existing analysis worker to process engine requests.
Both workers are separate local processes; restarting the API preserves queued work.
Player switching is deliberately unsupported and preserves historical ownership.

The frontend uses contracts generated from FastAPI's OpenAPI schema. See
[frontend API type generation](frontend/README.md#api-contracts) after schema changes.
See [Phase 13 verification](docs/PHASE13_VALIDATION.md) for checks and limitations.
Run `uv run python scripts/verify_phase13_http.py` with free ports 8000/5173 to
repeat the disposable API/Vite proxy and loopback verification.


## Local post-game coaching (Phase 14)

Apply migrations with `uv run alembic upgrade head`. Start Ollama locally with
`qwen3.5:4b-q4_K_M` installed. Configure `OLLAMA_NO_CLOUD=1` in the Ollama server
environment and restart it for server-level cloud disablement. The application
accepts loopback Ollama hosts and local model tags only; it never downloads models
or falls back to cloud inference.

The browser workflow above uses the combined worker. To run coaching separately,
stop the analysis worker and run:

```sh
uv run chess-coach coaching-worker
# Or process one queued coaching request:
uv run chess-coach coaching-worker --once
```

The standalone workers share a kernel guard. Stop the standalone coaching
worker before restarting analysis. This conservative memory policy uses
the existing local worker pattern; no queue service is required. Queued coaching
survives process exit, and interrupted generation requeues when its worker starts.

In **Games**, open a completed analysis, select a move, and choose
**Explain this move**. In **Coach**, choose **Generate historical coaching**
when the measured report has supported weaknesses. Requests are explicit, duplicate generation is guarded, and
saved coaching reopens without inference. The API exposes move explanation
GET/POST endpoints, `/api/v1/coaching-jobs/{job_id}`, read-only readiness at
`/api/v1/system/llm`, and historical coaching GET/POST at
`/api/v1/coaching/history` (window/color/time_class/profile_hash query filters).
Historical generation uses only supported Phase 12 weaknesses and linked moves.
Insufficient histories abstain without contacting the model.

GET retrieves a validated snapshot without Ollama. POST checks the current local
model digest and reuses its compatible cache, or creates a job. If Ollama is
unavailable, an existing validated result remains accessible. Evidence, model
digest, prompt/schema versions and all generation settings define cache identity.
Engine facts remain independent of generated prose. Mate is never converted to
centipawns, and the played continuation starts after the actual move.

Automated checks reject malformed responses, prohibited numeric/notation claims,
some board contradictions and unverified tactical assertions. They do **not**
prove arbitrary prose correctness. The UI says that explanations passed automated
checks; human coaching-quality release gates remain pending. See
[Phase 14 evaluation](docs/evaluation/phase14_baseline.md) and the
[human review rubric](evaluation/rubrics/coaching_quality.md).

```sh
uv run python -m chess_coach.evaluation.move_coaching --validate-only
uv run python -m chess_coach.evaluation.move_coaching --output evaluation/results/run.json
CHESS_COACH_REAL_OLLAMA=1 uv run pytest tests/api/test_coaching_routes.py -k real_ollama
```

Normal tests fake the model and require no Ollama or public network. The fixed
50-case synthetic development dataset is not a reviewed mistake benchmark and
does not satisfy the future 200-case held-out acceptance criteria. Human labels
and explanation-quality scores are needed before claiming the future model-quality
targets or publishing experimental model-suggested motifs.

## Motif evidence (Phase 15, experimental)

Run `uv run alembic upgrade head` to add independent event snapshots. For an
analyzed move by the tracked player, GET
`/api/v1/games/{game_id}/moves/{ply}/motif` to see verified events without
Ollama. POST to save the event snapshot and queue an optional experimental
suggestion through the same coaching worker. Poll the move's motif URL. Ollama
failure does not invalidate the event or engine analysis. The read-only
`/api/v1/system/motifs` endpoint checks schema and local model readiness.

The existing `qwen3.5:4b-q4_K_M` is used for development. Model suggestions
remain unpublished while the human quality gate is pending. See the
[smoke results and evaluation commands](docs/evaluation/model-selection.md).

## Personalized Training

Generate one-move puzzles from your mistakes in completed games after a
compatible local Stockfish analysis finishes. Run migrations, stop the analysis
worker, then use the tracked player ID and completed run's profile hash:

```sh
uv run alembic upgrade head
uv run chess-coach training generate --player-id 1 --profile PROFILE_HASH
```

Open **Training** to select a move, see the engine solution and continuation,
and review the source game. Generation rejects close alternatives and
unstable engine choices. The backend grades against the stored solution and
schedules the next review in UTC. Incorrect answers return after one day.
Consecutive correct answers extend reviews to 3, 7, 14, then 30 days.
Practice remains available with Stockfish and Ollama offline.

The Training page shows puzzle accuracy and, when enough comparable games
exist, the observed change in centipawn-scored critical errors after training
began. The game comparison is observational.

See the [training specification](docs/training-spec.md) for eligibility,
statistics, configuration and recovery, and the [verification record](docs/PHASE18_VALIDATION.md)
for the historical sample and browser checks.
