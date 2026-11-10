# Set up Chess Coach

Use a clean checkout on macOS with Git, uv, Python 3.14, Node 24, pnpm
12.15.0 and Stockfish. The checked tool versions are in the
[environment record](benchmarks/environment.md).

```sh
brew install uv node@24 stockfish
export PATH="$(brew --prefix node@24)/bin:$PATH"
npm install --global pnpm@12.15.0
uv python install 3.14
```

Use the following commands from the repository root for a **new** installation.
For an existing library, follow the [backup and upgrade guide](operations.md#backup-upgrade-and-restore).

```sh
uv sync --locked
pnpm --dir frontend install --frozen-lockfile
cp .env.example .env
uv run --locked alembic upgrade head
pnpm --dir frontend build
./scripts/start.sh
```

On macOS, you can also double-click `Chess Coach.command` in the repository
folder in Finder. It starts the packaged server and both workers, then opens
your default browser. Use it in place of the manual server and worker commands.
Keep its Terminal window open while using Chess Coach. Press Ctrl+C in that
window to stop the server and workers together.

Open [Chess Coach](http://127.0.0.1:8000). In another terminal, confirm the
server and database are ready.

```sh
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
```

Start each worker in its own terminal at the repository root.

```sh
uv run --locked chess-coach sync-worker
uv run --locked chess-coach analysis-worker --with-coaching
```

Enter a Chess.com username on **Sync**. Import completed games, then choose
**Analyze Pending Games**. Review individual moves under **Games** and recurring
patterns under **Coach**. See [training setup](../README.md#personalized-training)
for puzzle generation. Ctrl+C stops each local process.

For optional AI explanations, install Ollama, start it on loopback with
`OLLAMA_NO_CLOUD=1` in its server environment, and pull the tag configured
in `.env`.

```sh
ollama pull qwen3.5:4b-q4_K_M
ollama list
```

For Vite development, stop the packaged server and run `./scripts/dev.sh`.
The browser uses port 5173 and the API uses port 8000.

| Symptom | Check and recover |
| --- | --- |
| Packaged app refuses to start | Read the first launcher error. Run `uv run --locked chess-coach doctor`, check the frontend build and confirm port 8000 is free. |
| SQLite unavailable or schema outdated | Verify `CHESS_COACH_DATABASE_PATH` and disk access. Back up an existing library before applying migrations. |
| Stockfish unavailable | Check `command -v stockfish` and `uv run --locked chess-coach engine-check`. Set the executable path in `.env` if needed. |
| Ollama or model unavailable | Start the local server and run `ollama list`. Pull the configured tag if absent. |
| Chess.com rate limit or timeout | Read the sync result. Wait for the retry interval before running again. |
| Browser reports backend unavailable | Check the liveness and readiness URLs. In development, use the matching Vite launcher and API port. |
| Analysis interrupted | Restart the analysis worker with the same profile and inspect the saved run on **Sync**. |

The [operations guide](operations.md) covers backups, configuration and detailed
recovery. See [Testing](TESTING.md) for checks using disposable data.
