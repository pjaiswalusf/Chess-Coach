# Chess Coach

A local-first chess coach for completed games. Currently includes API liveness
and dependency status checks; game import, analysis, and coaching are not yet
implemented. Shared development rules live in [AGENTS.md](AGENTS.md).

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
- `GET /api/v1/system/status`: Stockfish UCI readiness, Ollama reachability,
  and configured model installation as separate states. HTTP 200 means the status
  report succeeded; inspect each dependency state to determine readiness.
- `/docs`: interactive API documentation.

Install Stockfish separately and set `CHESS_COACH_STOCKFISH_EXECUTABLE` if it is
not on PATH. Start Ollama and pull the model named by `CHESS_COACH_OLLAMA_MODEL`.
A model being installed does not prove it can successfully generate a response;
this status check does not load the model or run inference. Stockfish probing
starts a short-lived process for a UCI handshake, without analyzing positions.

Settings read `.env` from the current working directory; environment variables
override that file. Relative database paths are also relative to the working
directory. Launch from the repository root for consistent paths. The database
setting is reserved for the persistence feature; startup does not create a DB.

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
pre-FEN history remains unknown. No caching or cross-history reuse is implemented.
