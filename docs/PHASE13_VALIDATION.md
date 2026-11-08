# Phase 13 validation

Baseline: clean working tree, existing 499 tests passed, Ruff/mypy passed. The
locked environment was synchronized with uv. No new dependencies or migrations
were introduced. No real chess-history database was migrated or modified.

## Delivered

All 15 requested product/health operations, generated docs/OpenAPI, explicit
Pydantic contracts, request-scoped dependency injection, player configuration,
paginated games, compatible stored analysis, persistent sync admission/worker,
cross-operation admission, existing-worker analysis operations, and four projections
of the existing deterministic analytics report. Existing diagnostic extensions
remain available. Frontend API types and the existing analysis UI were updated
for the unified error format, public run statuses, and game-analysis envelope.
No coaching, arbitrary-position endpoint, full dashboard, infrastructure service,
new engine calculation, or new statistical formula was added.

## Final results

| Command | Observed result |
| --- | --- |
| `uv sync` | Passed; existing lock retained |
| `uv run ruff check .` | Passed |
| `uv run mypy src` | Passed, 78 source files |
| `uv run pytest -q` | 552 passed, 2 opt-in engine tests deselected |
| `uv run pytest tests/api -q` | 55 passed |
| `pnpm lint` (frontend) | Passed |
| `pnpm check` (frontend) | Passed, zero errors/warnings |
| `pnpm test` (frontend) | 5 passed |
| `pnpm build` (frontend) | Passed |
| `pnpm test:e2e` (frontend) | 3 passed, 1 opt-in real-engine workflow skipped |
| `uv run python scripts/verify_phase13_http.py` | Passed all five HTTP/proxy/listener checks |
| `git diff --check` | Passed |

Normal API tests use migrated temporary SQLite, fake engine/provider adapters,
and overridden system probes. They neither require real Stockfish/Ollama nor
use public network access. The normal suite still emits existing python-chess
asyncio and FastAPI TestClient/httpx deprecation warnings. Frontend tooling emits
existing Svelte/Vitest transform-hook and adapter-auto environment notices.
These were not suppressed or addressed by unrelated dependency upgrades.

## Evidence and failure drill

`tests/api/test_contracts.py` and migrated persistence tests cover empty player/
games/analytics, username validation and normalization, repeated player PUT,
unsupported switching, stable 25-game pagination, ID/query validation, pending
analysis, exact CP orientation/loss values, separate terminal mate representation,
analytics projection equality, invalid shared filters, durable acceptance and
polling, sync failures, restart recovery, queued/running/terminal transitions,
zero-new-work engine avoidance, source validation before sync completion,
cross-operation and same-operation concurrent submissions, database admission
failure, dependency degradation, safe exceptions, Host/Origin/Fetch Metadata,
JSON-only bodies, and explicit generated OpenAPI success/error schemas.
Existing engine/cache/analytics fixtures retain their deeper correctness gates.

The real HTTP drill launched Uvicorn and Vite on an isolated migrated database,
with a nonexistent Stockfish executable and unreachable local Ollama port. It
observed equivalent direct/proxy system JSON (excluding checked_at), a preserved
404 JSON error through Vite, a trusted-origin proxied player update visible in
the backend, accessible docs/OpenAPI, and lsof reporting 127.0.0.1:8000 only.
Both child servers and the temporary database were cleaned afterward. The browser
suite verified start/reload/cancel/retry, worker/error messaging, and mate display.
Failures were simulated on fixtures; no actual personal import or engine job was
started by the drill.

## Independent review

The requested read-only reviewer used `.cursor/agents/reviewer.md`, AGENTS.md,
the original playbook, the contract, source, and tests. It reproduced a
cross-profile provenance failure: a state could reference profile B's run while
returning profile A's moves. The fix requires requested profile, run profile,
analysis version and player ownership to match before compatibility validation.
A regression corrupts A while B is valid and verifies A returns incompatible
with no moves. The reviewer also identified list status/filter ambiguity;
list/detail processing status is now consistently persisted-state based, with
source/deep compatibility explicitly reserved for the analysis evidence read.
Both findings have regression tests and documented semantics.

Final reviewer verdict: **PASS for implementation, with operational
qualifications**. It independently verified Ruff/mypy, all 55 API tests, an earlier
full 552-test run, frontend lint/check, and diff whitespace. Parent-run build,
frontend unit/browser and live proxy results were reported separately rather than
misrepresented as independently rerun by the reviewer.

## Unverified and operational limits

- The two real-Stockfish tests and the opt-in real-engine browser recovery workflow
  were not run. Real Chess.com synchronization and real Ollama availability were
  not exercised. External adapters keep their existing designated integration runs.
- No p95 or representative large-history API latency budget was measured. Existing
  analytics validates/replays evidence and all-history reports can be expensive;
  analysis eligibility also validates compatibility. No new caching claim is made.
- System statistics check stored current-profile completion/source/move counts;
  they do not replay every engine-cache history during polling. Game evidence reads
  validate deeply. A found executable alone is unknown readiness; a live verified
  worker supplies availability/version.
- Sync acceptance is durable even while its worker is stopped. Start sync-worker
  for progress. Interrupted sync runs fail recoverably and a new run resumes
  archive checkpoints; queued sync IDs persist. Analysis resumes with the existing
  worker's profile/history-aware recovery. Read requests never perform recovery.
- The API supports one Chess.com player. Existing multiple-player databases need
  the CLI; switching and cross-account data attribution are deliberately rejected.
- Origin-less local clients remain trusted. The supported launcher binds loopback;
  the Host allowlist is additional protection, not authentication for remote hosting.
- Personalized coaching remains Phase 14. No model-quality or coverage measurement
  is asserted by this phase's validation record.
