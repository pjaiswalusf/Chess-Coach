# Local operations

Chess Coach is a local single-user application. It is not intended to be exposed
on a public network without authentication and additional security controls.

## Install on macOS

Follow the [setup guide](SETUP.md) from a Git clone.
The locked installs are `uv sync --locked` and
`pnpm --dir frontend install --frozen-lockfile`. The tested toolchain is Python
3.14, Node 24 and pnpm 12. Check `uv run --locked python --version`,
`node --version`, and `pnpm --version` if an install fails. Run
`uv run --locked chess-coach engine-check` to verify Stockfish and
`uv run --locked chess-coach doctor` to check configuration, SQLite, and the
optional engine and model. Install Chromium once with
`pnpm --dir frontend test:setup` for browser tests.

## Start and stop

| Mode | Command | Open |
| --- | --- | --- |
| Development | `./scripts/dev.sh` | `http://127.0.0.1:5173`; FastAPI is on port 8000 |
| Packaged | `./scripts/start.sh` | `http://127.0.0.1:8000` |

In development, Ctrl+C stops both servers, and an unexpected exit of either
server stops the session. Vite forwards API and health requests to FastAPI.
In packaged mode, run `pnpm --dir frontend build` before starting. FastAPI
serves the build and all API routes; it runs one worker without reload.
Stop the app before rebuilding its served assets.

The launchers start the application servers. For new work, run
`uv run --locked chess-coach sync-worker` and
`uv run --locked chess-coach analysis-worker --with-coaching` in separate
terminals. The analysis worker releases Stockfish before generating coaching.
Use Ctrl+C in each worker terminal before upgrading or restoring data. On
restart, the workers reconcile unfinished jobs with saved checkpoints.

## Configuration

The launchers use the repository as the working directory. Settings come from
`.env` there, with environment variables taking precedence. Relative paths are
resolved from the repository when using the launchers; use the same working
directory for Alembic, worker, and backup commands. `data/chess_coach.db` is
the default durable SQLite file and is outside the frontend build.

| Setting | Default | Purpose |
| --- | --- | --- |
| `CHESS_COACH_SERVE_FRONTEND` | `0` | Enable static serving in the direct ASGI app; the launchers select their modes automatically. |
| `CHESS_COACH_DATABASE_PATH` | `data/chess_coach.db` | SQLite database used by API, workers, Alembic and backup. |
| `CHESS_COACH_STOCKFISH_EXECUTABLE` | `stockfish` | Engine command on PATH or an absolute executable path. |
| `CHESS_COACH_STOCKFISH_THREADS` | `4` | Stockfish thread count. |
| `CHESS_COACH_STOCKFISH_HASH_MB` | `512` | Stockfish hash memory in MB. |
| `CHESS_COACH_STOCKFISH_NODES` / `CHESS_COACH_STOCKFISH_MAX_NODES` | `10000` / `10000000` | Default and maximum search node budget. |
| `CHESS_COACH_STOCKFISH_SEARCH_SECONDS` / `CHESS_COACH_STOCKFISH_TIMEOUT_SECONDS` | `3` / `10` | Search and UCI operation time limits in seconds. |
| `CHESS_COACH_OLLAMA_HOST` | `http://localhost:11434` | Loopback Ollama endpoint. |
| `CHESS_COACH_OLLAMA_MODEL` | `qwen3.5:4b-q4_K_M` | Installed local model tag. |
| `CHESS_COACH_LLM_TIMEOUT_SECONDS` / `CHESS_COACH_LLM_CONTEXT_TOKENS` / `CHESS_COACH_LLM_OUTPUT_TOKENS` | `90` / `4096` / `800` | Local generation limits. |
| `CHESS_COACH_LLM_KEEP_ALIVE` / `CHESS_COACH_LLM_THINK` | `0` / `false` | Model retention and thinking mode. |
| `CHESS_COACH_ANALYSIS_MIN_FREE_MB` | `256` | Minimum free space for analysis; readiness also requires at least 500 MiB. |
| `CHESS_COACH_TRAINING_STOCKFISH_THREADS` / `CHESS_COACH_TRAINING_CANDIDATE_LIMIT` / `CHESS_COACH_TRAINING_VERIFICATION_NODES` | `1` / `30` / `500000` | Puzzle verification budgets. |
| `CHESS_COACH_CHESSCOM_USERNAME` | unset | Optional initial Chess.com username. |
| `CHESS_COACH_LOG_LEVEL` / `CHESS_COACH_PGN_MAX_BYTES` | `INFO` / `1000000` | Backend log level and PGN size limit. |

## Health and troubleshooting

- `GET /health/live` checks whether FastAPI responds; `/health` is the
  legacy liveness endpoint. Neither checks external services.
- `GET /health/ready` checks the data directory, SQLite file and migration
  revision, and the frontend build in packaged mode. A core failure returns a
  diagnostic code and HTTP 503. Packaged startup refuses an invalid core
  setup before listening.
- `GET /api/v1/system` separates library health from engine and model
  availability; `/api/v1/system/health` supplies suggested recovery steps.
  Missing Stockfish prevents new analysis, and missing Ollama prevents new
  AI explanations. Neither prevents access to stored work. Status checks do
  not load the model, analyze a position, or contact Chess.com.

| Symptom | Verify and fix |
| --- | --- |
| Port 8000 or 5173 already in use | Run `lsof -nP -iTCP:8000 -sTCP:LISTEN` or substitute `5173`. Stop the old session from its own terminal and retry. |
| Frontend build missing or incomplete | Check for `frontend/build/index.html` and `frontend/build/_app/immutable`. Run `pnpm --dir frontend build` and restart. |
| Migration mismatch or missing database | Run `uv run --locked alembic current` and `uv run --locked alembic heads`. Confirm the configured path, then use the upgrade steps below. |
| Database or directory is read-only | Run the doctor command; check file and directory ownership, permissions and available space. Restore write access for your account or restore a verified backup. |
| Ollama unavailable or model missing | Check the configured address, run `ollama list`, start the local service or pull the configured model, then refresh System. |
| Stockfish unavailable | Run `uv run --locked chess-coach engine-check`. Install Stockfish or set its executable path, then restart the analysis worker. |
| API returns 404 | Confirm the URL against `http://127.0.0.1:8000/docs` and check the requested ID. Unknown API URLs return JSON. |
| Refreshing a Svelte route gives 404 | Use the packaged server on port 8000 or Vite on 5173. Check that the URL is an app page and rebuild the packaged assets if needed. A command-line probe of a client route should send `Accept: text/html`. |
| Static JavaScript returns HTML | Inspect the Network tab for the asset URL and content type. Rebuild with the server stopped, then refresh. A missing script must return 404; check for an old server or proxy if it returns HTML. |

For client routes in packaged mode, FastAPI sends the app shell and Svelte
renders a not-found page for an invalid route. API and asset requests retain
their HTTP error status.

## Backup, upgrade, and restore

Use the same `.env` and database path throughout. Before an upgrade, stop the
API and both job workers and record the counts shown in System and Puzzles.
Use the SQLite backup API rather than copying a live database file; it includes
committed data in the WAL. Run from the repository root:

```sh
uv run --locked python scripts/backup.py
```

The command prints the path to the new snapshot in `backups/` only after SQLite's
`integrity_check` returns `ok`. Keep the snapshot separately from the app files.
Reinstall from the lockfiles, then run:

```sh
uv run --locked alembic current
uv run --locked alembic heads
uv run --locked alembic upgrade head
pnpm --dir frontend build
./scripts/start.sh
```

Check readiness, compare counts, and open a saved game and report. The launcher
checks compatibility without creating, replacing, or migrating the database.

To restore, stop the app and all workers. Move the current database and any
matching `-wal`, `-shm`, and `-journal` files together to a separate recovery
directory so none of those sidecars remain at the original location. Copy the
verified snapshot to the configured database path. Run
`uv run --locked chess-coach doctor --deep` to check integrity and the schema.
If the snapshot has an older revision, back it up again and apply migrations
before restarting. Confirm counts and saved reviews before discarding anything.

## Packaging checks

With the frontend built and ports 8000 and 5173 free:

```sh
CHESS_COACH_TEST_LAUNCHERS=1 uv run --locked pytest tests/integration/test_local_launchers.py
pnpm --dir frontend test:e2e
```

The launcher tests and packaged browser test provision disposable SQLite files.
For a clean-install rehearsal, use a separate checkout without `.env`, run the
README setup, then run the checks in [AGENTS.md](../AGENTS.md#completion-checks).
For an upgrade rehearsal, use a copy of a fixture database with saved games and
reports and follow the backup procedure above.
