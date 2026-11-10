# Chess Coach frontend

SvelteKit and TypeScript frontend. Shared architecture, Tailwind styling rules,
and completion checks live in [AGENTS.md](../AGENTS.md).

## Setup

From this directory:

```sh
pnpm install --frozen-lockfile
pnpm test:setup
```

The setup command installs Chromium for component and end-to-end tests. Repeat it
when the Playwright browser version changes. Test execution does not download
browsers or install dependencies.

## Development

From the repository root, run `./scripts/dev.sh` after completing the
[local setup](../README.md#run-locally-on-macos). Vite binds to
`127.0.0.1:5173` and forwards `/health` and `/api/*` to FastAPI on `127.0.0.1:8000`.
The local build preview uses the same proxy on `127.0.0.1:4173`. Neither mode
enables CORS. System refreshes process health and dependency diagnostics separately.
Sync rediscovers persistent runs when opened. Dashboard, Games, and Coach read
fresh data on entry; changing a Games filter or coaching window refreshes from
the backend and preserves the selection in the URL. Job polling uses GET only,
one request at a time per run, with capped retry delays on disconnection.

## API contracts

After changing a FastAPI route or Pydantic schema, run this from the repository root:

```sh
uv run python scripts/export_openapi.py
pnpm --dir frontend run api:types
pnpm --dir frontend check
```

Commit the snapshot and generated declaration together. The exporter calls the
same FastAPI schema builder that serves `/openapi.json` and does not need a running
server. The generator consumes the local snapshot. It declares a TypeScript 5
peer range, so pnpm reports a warning with the project's TypeScript 6. Generation
and type checking have been verified with the versions in the lockfile.

API requests go through `src/lib/api/`. Use generated types for endpoint contracts,
and validate the response fields a screen needs when malformed data could look
like a valid empty or healthy state. Retry requests explicitly. A timeout on a
mutation can occur after the backend accepts the operation.

## Tests and build

- `pnpm lint`: Prettier and ESLint checks.
- `pnpm check`: Svelte and TypeScript checks.
- `pnpm test`: run unit and browser component tests once.
- `pnpm test:unit`: run tests in watch mode.
- `pnpm test:e2e`: build the app and run Playwright workflows, including a packaged smoke test with FastAPI on port 8000.
- `pnpm build`: generate the static app in `frontend/build/` for `./scripts/start.sh`.
- `pnpm preview`: preview the production build.

With ports 5173 and 8000 free and the root Python environment synced, run
`PHASE16_LIVE=1 pnpm test:e2e recovery-live.spec.ts` from this directory. It uses a
temporary migrated database, disables access to real Stockfish and Ollama, and
verifies browser behavior through Vite while stopping and restarting FastAPI.
Use `PHASE16_LIVE=preview` to run the same check through the build preview.

Style application markup with Tailwind classes. `src/routes/layout.css` contains
only Tailwind setup.
