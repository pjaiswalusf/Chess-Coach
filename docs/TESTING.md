# Testing

Install from both lockfiles. Install Chromium once after dependency installation
or a Playwright browser upgrade.

```sh
uv sync --locked --dev
uv run --locked ruff check .
uv run --locked mypy src
uv run --locked pytest

cd frontend
pnpm install --frozen-lockfile
pnpm test:setup
pnpm lint
pnpm check
pnpm test
pnpm build
CI=1 pnpm test:e2e
```

GitHub Actions separates **Backend checks**, **Frontend checks**, and
**E2E browser tests**. Both browser-dependent jobs install Chromium and Linux
system dependencies before running tests. The E2E job starts after both build
gates pass. A failed Playwright step uploads synthetic diagnostics for seven days.
CI treats a test that only passes on retry as a failed gate.

## What runs offline

- Pytest redirects configuration to a per-test SQLite path and guards real
  HTTPX requests. Stockfish and real Ollama smoke tests are opt-in.
- Playwright starts the built frontend on port 4173. The complete workflow test
  starts its own FastAPI process on port 8001 with a migrated temporary
  database and fake source, engine, and model adapters. The browser checks
  fixture identity through the proxy before any mutation. The test covers
  source failures, import quarantine, saved analysis, game review, coaching,
  persisted training attempts, and API restart with the model offline.
- Other browser specs check focused UI states with intercepted responses or a
  disposable packaged instance. Real-engine and custom training database tests
  are opt-in.

To exercise real Stockfish independently, run
`uv run --locked pytest -m engine tests/integration/test_stockfish_real.py`.

## Release checks

Use GitHub rules for `main` to require the three CI job names above. To prove
the hosted gates reject defects, use disposable PR commits with one deliberate
backend lint failure and one frontend type error, then rerun at the corrected
revision. Keep real databases, archives and traces from personal sessions
outside release artifacts.

Investigate the first failing step and rerun the affected gate after correcting
it. Inspect the Playwright report for browser failures. Repeated clean runs are
needed to close a flaky-test investigation. A model evaluation failure goes
into the evaluation record. A privacy finding blocks publication until the
affected refs and copies are assessed.
