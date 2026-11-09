# Phase 17 product UI validation

The product workflow is available in the browser once the loopback services and
workers are running. See the [setup instructions](../README.md#frontend-setup).
Training remains out of scope.

| Gate | Verification |
| --- | --- |
| Foundation | FastAPI and Vite started independently; the Vite proxy returned liveness. The OpenAPI snapshot and TypeScript declarations are generated from the app. API and browser tests cover loading, errors, empty results, retry, and missing routes. |
| Dashboard | Browser fixtures cover empty, partial, complete, malformed, and failed responses. Counts, phase rates, opening evidence, and category rankings come from the backend. Trend and conversion tests cover minimum support. |
| Sync | Browser tests exercise validation, one admission, reload, reconnect, terminal polling, a rejected admission, and an existing run. API tests race two callers against SQLite and reject an unknown verified username before binding the library. |
| Games and review | Tests cover 0, 1, 25, and 26 results, filter resets, Black player results and ratings, keyboard navigation, and 375-pixel board rendering. The review projects stored FEN, SAN, scores, best moves, PVs, and severity. Tests exercise custom starts, promotion, invalid positions, mate, and escaping of imported text. |
| Coach | The selected window changes the backend request and survives reload. Stale reads are cancelled. Historical advice is bound to the exact measured report, and evidence links open the recorded profile and ply. Ollama failures preserve deterministic evidence. |
| System and local security | FastAPI process status, database, Stockfish, Ollama service and model, and active work are distinct. The live proxy test rejects untrusted-origin writes and confirms no cross-origin read header. System reads start no engine or model work. |
| Integration | Playwright completes Sync → Analyze → Games → critical position → Coach → evidence link with deterministic HTTP fixtures. A read-only analytics regression test proves freshly analyzed games produce phase evidence without precomputed features, and that derived and stored projections agree. The independent reviewer reported no remaining P0 or P1 issues. |

Required backend checks: Ruff and mypy passed; pytest had 637 passes, one
opt-in Ollama skip, and two real-engine tests deselected by the default command.
Required frontend checks: lint, type check, and build passed; Vitest had 34
passes; default Playwright had 37 passes and two opt-in tests skipped.
Both opt-in tests subsequently passed through the build preview with
`PHASE16_LIVE=preview PHASE10_REAL=1 pnpm test:e2e recovery-live.spec.ts analysis-real.e2e.ts --workers=1`.
That run verified real FastAPI outage and restart, trusted-origin enforcement,
and ten completed fixture games with real Stockfish: worker interruption and
resume, zero new searches on a compatible rerun, reanalysis after a budget change,
phase evidence without offline extraction, and final-position review. The
FastAPI outage and origin check also passed through the development proxy.

Public Chess.com synchronization and real Ollama inference are outside this
verification run. The browser workflow and degraded cases use fixtures; the
backend tests exercise their real persistence and admission logic. Large
all-history reports without feature snapshots may take longer because features
are derived from validated moves on read.
