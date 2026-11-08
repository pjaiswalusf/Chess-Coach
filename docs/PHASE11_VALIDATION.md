# Phase 11 validation — 2026-11-08

Implemented on `feat/deterministic-features`. Baseline: clean worktree, Ruff/mypy
passing, 329 tests passing with two opt-in engine tests excluded.

## Delivered

Typed feature inputs/outputs, fixed V1 policy, four focused analytics modules,
source-aligned replay, board/material/development/context/clock facts, additive
Alembic migration `f11a001`, atomic snapshot repository, offline CLI, and structured
per-run/per-game diagnostics. No frontend, FastAPI route, engine algorithm, LLM,
or dependency changes. Existing application logging is used rather than adding
`structlog`. See [semantics and operation](FEATURES.md).

## Verification

| Check | Result |
| --- | --- |
| `uv run ruff check .` | Passed |
| `uv run mypy src` | Passed, 58 source files |
| `uv run pytest --cov=chess_coach --cov-report=json --cov-report=term -q` | 393 passed; 2 real-engine tests deselected |
| Fresh migration, model comparison, downgrade/reupgrade, legacy preservation | Passed in full suite |
| `git diff --check` | Passed |
| Core feature coverage | 232/232 executable lines, 100% |
| Overall backend coverage | 2401/2567 executable lines, 93.53% |

Core subset: `analytics/{clocks,feature_config,features,phases}.py` and
`domain/feature_models.py`. Coverage includes all production files, including
unimported drafts. Line coverage is a diagnostic, not a claim of exhaustive chess
correctness. The existing python-chess asyncio deprecation warning remains.

The 64 added tests include hand-labeled tactical/material/phase cases, both colors,
clock unknowns/increment/explicit elapsed/pressure before the move, original minor
identities, king movement versus castling, optional engine degradation, invalid
best moves, FEN/score contradictions, no fabricated mate CP, determinism, snapshot
round trips and idempotency, input/profile/version isolation, failed-insert rollback,
interruption/retry, concurrent finalizers, corrupt payload repair, source completion,
CLI behavior, and truncated-save rejection. Historical fixtures cover short tactical,
queenless middlegame and long endgame games with independently inspected selected
piece counts and moves documented in their fixture README.

## Benchmark

A read-only backup of the existing Phase 10 corpus was migrated and processed in
an isolated database. Subprocess creation and sockets were patched to fail during
extraction and the repeat. Source databases and the live application database were
not migrated or modified.

| Metric | Result |
| --- | ---: |
| Unique historical completed games | 30 |
| Plies | 1,768 |
| Extraction seconds | 0.1730 |
| Persistence seconds | 0.1294 |
| Total wall seconds (includes replay/loading) | 0.4274 |
| Features / extraction second | 10,219 |
| Failed games | 0 |
| Missing after clocks / plies | 465/1768 = 26.30% |
| Missing before engine scores / plies | 0/1768 = 0% |
| Before mate scores (CP context unknown) | 107 |
| Opening / middle / endgame plies | 590 / 799 / 379 |
| Captures / checks / castling | 450 / 198 / 39 |
| Early queen movements / advantage-loss observations | 69 / 18 |
| Repeat skipped games | 30 |
| Subprocess / network calls | 0 / 0 |

These timings are observations on this machine, not a universal performance target.
The same corpus's Phase 10 engine time was 20.096 seconds; the feature pass reused
its evidence and did not repeat any engine searches. The first-N sample is not
random, and its distributions are sanity checks, not population claims. Raw output:
[phase11.json](benchmarks/phase11.json). Reproduce with a fresh destination using
`scripts/benchmark_phase11.py --source ... --database ... --output ...` through uv.

## Review and remaining limits

Independent verification uses the existing `.cursor/agents/reviewer.md` profile.
Initial review found four issues, all fixed with regressions: annotation-free
initial pressure, truncated persistence, unversioned custom threshold overrides,
and contradictory/nonterminal-mate-zero score evidence. Final independent review:
**implementation PASS**, with the larger-sample benchmark explicitly unverified.
The reviewer independently reproduced Ruff, mypy, all 393 tests, diff checks and
coverage counts, and checked benchmark arithmetic. A minor follow-up making the
benchmark's sample label dynamic for arbitrary source corpora was also applied.

The requested approximate 50–100 already-analyzed-game sample was **not available**.
Only 30 unique games had persisted engine evidence; the 10-game and recovery samples
overlap, and the live database has zero analyzed games. No samples were duplicated
and no new Stockfish work was launched to inflate this measurement. The larger-sample
benchmark remains unverified. Implementation release gates are supported by the tests and independent review
above, with this explicit benchmark-size limitation.

Phase classification and timing remain heuristics. Unknown custom-start development,
missing clocks/evaluations and mate CP context stay unknown. Critical-error-on-fast
features remain unknown until upstream severity evidence exists. This phase makes
no claims about tactical motifs, LLM quality, or causation in player behavior.
