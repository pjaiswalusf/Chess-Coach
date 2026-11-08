# Chess Coach

A local-first chess coach for completed games. Includes historical imports, PGN
validation, persistent Stockfish analysis, resumable local runs, and a Svelte UI.
Offline deterministic player analytics are available; LLM coaching is not yet implemented. Shared development rules live in [AGENTS.md](AGENTS.md).

## Backend setup

Use Python 3.14 and uv. Run commands from the repository root:

```sh
uv sync
cp .env.example .env
uv run chess-coach
```

The CLI starts FastAPI on `127.0.0.1:8000`. For development with automatic reload:

```sh
uv run uvicorn chess_coach.api.app:app --host 127.0.0.1 --port 8000 --reload
```

- `GET /health`: API liveness; does not require Stockfish or Ollama.
- `GET /api/v1/system`: component availability and stored/analysed game counts.
  Database failures produce unavailable counts, and optional dependency outages
  degrade the report without breaking liveness.
- `GET /api/v1/system/status`: retained detailed dependency diagnostics.
- `/docs`: interactive API documentation.

Install Stockfish separately and set `CHESS_COACH_STOCKFISH_EXECUTABLE` if it is
not on PATH. Start Ollama and pull the model named by `CHESS_COACH_OLLAMA_MODEL`.
A model being installed does not prove it can successfully generate a response;
this status check does not load the model or run inference. API polling never
starts Stockfish: executable detection alone is unknown readiness; a verified
registered analysis worker supplies current availability and engine version.

Settings read `.env` from the current working directory; environment variables
override that file. Relative database paths are also relative to the working
directory. Launch from the repository root for consistent paths. Run `uv run alembic upgrade head` to create or upgrade the configured database.

## Frontend setup

In a second terminal:

```sh
cd frontend
pnpm install
pnpm dev
```

Vite forwards `/api` requests to the backend on port 8000. Frontend test setup
and commands are documented in [frontend/README.md](frontend/README.md).
Backend checks are listed in [AGENTS.md](AGENTS.md#completion-checks).

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

Run `uv run chess-coach doctor` for a fixed-position startup, ping, legal-PV,
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

The existing analysis UI uses the updated run statuses and analysis response.
Regenerate its types with `uv run python scripts/generate_api_types.py`, then run
`pnpm exec prettier --write src/lib/api/generated.ts` from `frontend/`.
See [Phase 13 verification](docs/PHASE13_VALIDATION.md) for checks and limitations.
Run `uv run python scripts/verify_phase13_http.py` with free ports 8000/5173 to
repeat the disposable API/Vite proxy and loopback verification.


## Local post-game coaching (Phase 14)

Apply migrations with `uv run alembic upgrade head`. Start Ollama locally with
`qwen3.5:4b-q4_K_M` installed. Configure `OLLAMA_NO_CLOUD=1` in the Ollama server
environment and restart it for server-level cloud disablement. The application
accepts loopback Ollama hosts and local model tags only; it never downloads models
or falls back to cloud inference.

After completing engine analysis, stop the analysis worker and run:

```sh
uv run chess-coach coaching-worker
# Or process one queued coaching request:
uv run chess-coach coaching-worker --once
```

The two workers share a kernel guard and cannot run simultaneously. Stop the
coaching worker before restarting analysis. This conservative memory policy uses
the existing local worker pattern; no queue service is required. Queued coaching
survives process exit, and interrupted generation requeues when its worker starts.

In the existing game review, view saved moves, choose **Explain ply**, then
**Explain this move**. Requests are explicit, duplicate generation is guarded, and
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
and explanation-quality scores must be supplied before release approval.
