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
