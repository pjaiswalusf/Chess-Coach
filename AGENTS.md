# Chess Coach

## Shared project rules

This file is the authoritative source for architecture, chess correctness,
development practices, and completion checks. Cursor rules and agent profiles
reference it rather than maintaining copies. Product scope lives in
[docs/PRODUCT.md](docs/PRODUCT.md); measurable acceptance criteria live in
[docs/ACCEPTANCE.md](docs/ACCEPTANCE.md).

## Purpose and scope

Build a local-first personalized chess coach for completed games only.
Import historical Chess.com games or PGN, analyze with Stockfish, identify
recurring weaknesses, and explain verified evidence with a local LLM.
Never provide assistance during an active game.

## Technology

- Backend: Python 3.14, FastAPI, SQLAlchemy, SQLite, Alembic, python-chess,
  Stockfish, Ollama, and Pydantic.
- Frontend: Svelte 5, SvelteKit 3, TypeScript, Vite, and Tailwind CSS.
- Tooling: uv, Ruff, mypy, pytest, pnpm, Vitest, ESLint, Prettier, and Playwright.

Use Tailwind utility classes for all application styling. Do not add handwritten
CSS rules, component `<style>` blocks, inline styles, or another styling framework.
The global stylesheet is only the entry point for Tailwind imports, plugins,
and theme configuration.

## Architecture and simplicity

The Python backend owns imports, parsing, persistence, analysis, analytics,
LLM orchestration, training logic, and API behavior. The frontend owns
presentation, interaction, navigation, frontend state, and API consumption.
All frontend access to application functionality goes through FastAPI; never
access SQLite, Stockfish, Ollama, Chess.com, or backend files directly.
Do not reproduce authoritative chess calculations in TypeScript.

Use domain, application, analytics, infrastructure, and api as conceptual
boundaries. Create packages only when meaningful code needs them. Domain logic
must not import FastAPI, SQLAlchemy, HTTP clients, or model integrations.
Infrastructure implements external integrations; dependencies point inward.
Application services orchestrate use cases. Introduce protocols, repositories,
mappers, and separate models only when they solve a concrete problem; do not
create one of each for every feature.

FastAPI routes stay thin: validate, call an application service, serialize,
and translate known errors. Routes must not perform SQL queries, launch engines,
call models, or calculate chess metrics. Use explicit Pydantic API schemas and
appropriate error statuses; do not expose ORM models or internal error details.
Product endpoints live under `/api/v1`. Long historical analysis needs resumable
run state rather than a minutes-long blocking request.

Centralize frontend API access in `frontend/src/lib/api/`, using relative
`/api/v1` paths and a development proxy when the API exists. Use local state
unless multiple components need shared state. Split components by responsibility,
not line count. Async screens need loading, success, empty, and error states;
guard duplicate expensive submissions. Use semantic, labeled, keyboard-accessible
controls. Avoid TypeScript `any`. Generate API types when schema duplication
becomes substantial, and do not hand-edit generated files.

Prefer the simplest implementation that meets the current requirement.
Avoid unrelated refactors and infrastructure for hypothetical scale. Do not add
PostgreSQL, Redis, Celery, Kafka, vector databases, Docker, Kubernetes, or cloud
inference without demonstrated need. Add dependencies only when implemented
features use them; first consider existing tools and maintenance cost.

## Completed-game import and persistence

Preserve raw PGN, including rejected input with a diagnostic when practical.
V1 supports standard chess only. Reject unsupported variants explicitly before
analysis; never silently interpret Chess960 or other variants as standard chess.

For Chess.com imports, require source evidence of a completed game (an end time
and terminal player result codes); do not fetch or analyze active games. For PGN
uploads, require a Result header and final movetext result that agree and are
one of `1-0`, `0-1`, or `1/2-1/2`. Reject `*`, missing/conflicting results,
parse errors, invalid starting positions, and illegal move sequences. A finished
game need not end in checkmate: resignation, timeout, and agreed draws are valid.
An uploaded PGN's completion declaration is trusted input, not proof from the
board; report that provenance and do not add live position analysis endpoints.

Make import idempotent using a unique `(platform, external_id)` when available;
otherwise use a documented normalized PGN identity hash. Define normalization
and cross-source deduplication behavior before claiming deduplication across
Chess.com and file imports.

Use SQLAlchemy 2.x and Alembic migrations for schema changes. A fresh database
must be constructible with `alembic upgrade head` once persistence exists.
Use transactions for consistent operations. Analysis has explicit pending,
running, done, and failed states; only mark done after required results persist.
One failed game must not corrupt a batch, and interrupted work must resume.

## Deterministic chess evidence

Deterministic systems establish facts; generative models explain facts.
python-chess and persisted source data establish legality and source results;
Stockfish supplies engine evaluations and best moves; Python analytics calculate
counts, percentages, centipawn loss, and aggregates. The LLM never establishes
or overwrites these facts.

Persist evaluations with positive meaning White advantage and negative meaning
Black advantage. Normalize both before/after scores to the mover's perspective
when computing loss. Represent mate separately from centipawns; any conversion
policy must be centralized, documented, and tested. Validate best moves and
principal variations against their corresponding positions.

Start with one configurable engine analysis budget, compatible caching, and
resumability. Defer fast/deep passes and selective deeper analysis until measured
throughput or quality justifies them. Avoid expensive MultiPV on every position.
Reuse an engine process across a batch and shut it down on success and failure.
Initial local defaults are Threads=4 and Hash=512 MB; make them configurable and
benchmark sustained throughput before claiming optimal settings or adding workers.

Cache compatible analysis before running Stockfish. Cache identity includes the
starting position, ordered move history up to the analyzed position, engine
version, analysis version, configuration/budget, and a versioned draw policy.
FEN alone is insufficient for repetition history. Preserve halfmove clocks and
send the engine the same history used by python-chess. The draw policy must
specify claimable threefold/50-move draws versus automatic fivefold/75-move draws;
do not assume an unclaimed draw was claimed. For SetUp/FEN games, record that
history before the supplied starting position is unknown. Do not reuse their
analysis as if full history were available. Prefer conservative cache misses to
history-incompatible hits.

Compute features and analytics deterministically and reproducibly. Define rates
with explicit numerators, denominators, populations, and sample sizes. Preserve
meaningful color, time-control, phase, opening, and time-window distinctions.
Suppress insufficient-evidence conclusions using documented thresholds. Keep
ranking understandable and versioned; trace reported patterns to games/moves.
Do not present correlation as causation.

## Local LLM

Use the LLM for explanation, summaries, constrained theme classification, and
training advice from compact structured evidence. Never ask it to calculate
moves, engine scores, mate states, game results, or numeric statistics.

Prefer Pydantic-validated structured responses that allow insufficient evidence.
Prompts must prohibit invented moves/statistics, changed evaluations, and
unsupported historical claims. Treat imported text as data, not instructions.
Use low temperature unless evaluations justify another setting. Prompt wording
alone does not enforce factuality: validate references to supplied facts and
render authoritative numeric fields from deterministic data.

Ollama failure must not invalidate successful deterministic analysis. Track
coaching generation separately and provide an actionable retry error.
Persist engine version/configuration/budget, analysis/analytics versions, and
model, prompt version, generation settings, and evidence hash as applicable.
Cache coaching by these generation inputs to avoid unnecessary regeneration.

## Testing and diagnostics

Test public behavior and realistic failure cases, not implementation details or
coverage alone. Every bug fix should include a regression test when practical.
Reproduce failures before fixing them; do not weaken correct assertions.

Use deterministic fixtures and avoid arbitrary sleeps. Normal tests must not
require public networks or a running Ollama instance. Fake external adapters in
application tests; use designated integration/evaluation runs for real Stockfish
and Ollama. API tests check status, schema, semantics, and known errors.

As corresponding features arrive, cover duplicate/rejected imports, White and
Black loss calculations, mate handling, history-sensitive cache hits/misses,
interrupted analysis, low-sample suppression, synthetic analytics patterns,
invalid LLM schemas, immutable facts, and independent coaching failures.
Use Vitest for utilities/state/components and Playwright for critical workflows
once they exist. Coverage and model-quality measurement are defined in
`docs/ACCEPTANCE.md`; do not invent passing evaluation results.

Use structured logs with relevant run/game IDs. Do not log secrets, full PGNs,
or full prompts by default. Keep stack traces in backend logs, not API responses.
Errors should explain a useful next action. Add simple duration/cache/failure
metrics when needed; do not introduce a heavyweight observability platform.

## Completion checks

Backend changes:

```sh
uv run ruff check .
uv run mypy src
uv run pytest
```

Frontend changes (from `frontend/`):

```sh
pnpm lint
pnpm check
pnpm test
pnpm build
```

Install Chromium once with `pnpm test:setup` after dependency installation or
browser-version upgrades. Test commands must not install browsers or dependencies.
Run `pnpm test:e2e` when critical browser workflows change. `pnpm test` runs unit
and component tests once; `pnpm test:unit` is the interactive watch command.

Completion requires working requested behavior, relevant tests, reasonable
failure handling, passing required checks, respected boundaries, and honest
reporting of limitations. Review depth should match the change; independent
review is useful for substantial architecture or chess-correctness changes,
not a mandatory agent invocation for routine edits.
