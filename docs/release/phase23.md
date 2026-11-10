# Phase 23 release audit

**Release gate failed.** The privacy finding below blocks publication. Local
checks, hosted checks, and human-reviewed evidence are tracked separately.

## Privacy and dependency audit

- The Phase 23 working tree and branch history omit the historical benchmark
  database and raw exports. A legacy commit still reachable from public
  `main` contains both. The commit was also reachable by its direct GitHub
  commit endpoint at the time of the audit. The release gate requires the
  maintainer to address the affected public refs and consider existing forks
  and copies before publication.
- Gitleaks 8.30.1 scanned the available Git refs with redacted output and
  found zero matching secrets. File-history review was a separate check and
  found the game-data exposure above. Current rules for `main` returned no
  required checks, and the branch endpoint reported it unprotected.
- The Python lock export passed `pip-audit` with no known advisories.
  `pnpm audit --audit-level=high` reported zero high or critical advisories.
  The full npm audit found three development dependency advisories.
  [Selector parser](https://github.com/advisories/GHSA-rj75-hqrm-r3gf) and
  [minimatch](https://github.com/advisories/GHSA-g3hv-75wg-m249) are moderate.
  [deepmerge](https://github.com/advisories/GHSA-gcqx-w48m-w2h4) is low.
- The setup installs dependencies separately. Stockfish is GPLv3,
  python-chess is GPLv3 or later, and the selected Ollama model tag lists
  Apache 2.0. Review source and notice obligations for any future bundled
  distribution and compatibility of project licensing before that release.
  [Stockfish license](https://github.com/official-stockfish/Stockfish#terms-of-use),
  [python-chess license](https://github.com/niklasf/python-chess#license),
  [model tag license](https://registry.ollama.com/library/qwen3.5%3A4b-q4_K_M).

## Claim evidence

| Claim | Evidence |
| --- | --- |
| Incremental sync preserves existing games | Complete browser workflow repeats synthetic sync and verifies the stored game total. The API tests cover concurrent job admission. |
| Compatible cache entries avoid repeat engine calls | Fixed-game cold/warm comparison in [Benchmarks](../BENCHMARKS.md). |
| White/Black scores and mate handling | Domain and opt-in real Stockfish regression tests. |
| Structured generation and motif accuracy | First-response measurements and limitations in [Evaluation](../EVALUATION.md). Accuracy and human usefulness require a reviewed holdout. |
| Practice is saved through restart | The complete browser workflow submits a puzzle attempt, restarts the API and verifies the count. |
| Degraded operation preserves stored evidence | Health, worker restart and network failure cases in [Reliability](../reliability/phase20-report.md). |

## Phase gates

| Stage | Status | Evidence or remaining prerequisite |
| --- | --- | --- |
| 23.0 Preflight | FAIL | Branch, lockfiles, synthetic fixtures, machine inventory and baseline passed. Public history contains private game data. |
| 23.1 Backend CI | BLOCKED | Locked local install, Ruff, mypy and 717 pytest passes. Three engine tests and seven launcher tests passed in separate opt-in runs. The default suite skipped seven opt-in cases. Deliberate local Ruff failure and clean recovery verified. Hosted result pending the privacy gate. |
| 23.2 Frontend CI | BLOCKED | Frozen install, lint, Svelte check, 37 Vitest tests and production build passed. Deliberate local type failure and clean recovery verified. Hosted result pending. |
| 23.3 Browser CI | BLOCKED | Three local CI-mode runs each passed 40 tests with three opt-in skips and zero retries. Real FastAPI, migrated temporary SQLite and offline adapters exercised the full workflow. A deliberate local browser failure produced HTML, traces and screenshots. Linux execution and hosted artifact upload are pending. |
| 23.4 CI and operational safety | FAIL | Workflow uses read-only permissions and checksum-verified actionlint passed. Liveness, readiness and degraded services are covered by tests. Required checks are missing on public main. |
| 23.5 Setup | PASS | A disposable clone with fresh project dependencies applied all migrations, built the UI, served the asset entry point, and passed liveness and readiness. System-level tools were already installed. |
| 23.6 Architecture | PASS | [Architecture](../architecture.md) maps the local API, storage, worker and capability boundaries to the implementation. |
| 23.7 ADRs | PASS | [Decision records](../adr/README.md) cover seven implemented tradeoffs with evidence and revisit criteria. |
| 23.8 Evaluation | BLOCKED | Real development inference and deterministic baseline are recorded. An adjudicated holdout is missing, and only one of 12 move explanations passed the automatic guard. |
| 23.9 Benchmarks | PASS | Actual M5 engine, model, resource overlap and cache trials are recorded. Four sweep searches failed validation. Peak memory pressure and long-run thermal behavior remain unmeasured. |
| 23.10 Demonstration | PASS | Five screenshots and a silent walkthrough use synthetic inputs. The [demo index](../demo/README.md) identifies simulated scores, prose and capabilities. |
| 23.11 Release | FAIL | A disposable backup and restore preserved seven games, 27 move analyses and two run rows after abrupt process exit. Integrity and foreign key checks passed. The independent reviewer found no additional blocker and returned FAIL on public history. |

## Acceptance scorecard

| Criterion | Status |
| --- | --- |
| Backend hosted CI passes from locked dependencies | BLOCKED |
| Frontend hosted CI passes from locked dependencies | BLOCKED |
| E2E passes with isolated fixture storage locally | PASS |
| Deliberate errors turn hosted CI red and corrected runs recover | BLOCKED |
| Required status checks protect main | FAIL |
| Public history is free of secrets and private game data | FAIL |
| Core and degraded application health verified | PASS |
| Ollama, Stockfish and source failures exercised | PASS |
| Analysis recovery and fixture data preservation verified | PASS |
| CI suite exercises no real Chess.com or model service | PASS locally |
| Independently labeled holdout and metric definitions | BLOCKED |
| Actual move and motif development evaluation reported | PASS |
| M5 Air measurements reported | PASS |
| Cache effectiveness measured | PASS |
| Current numerical claims trace to evidence | PASS |
| Fresh-clone setup verified | PASS |
| Architecture and failure boundaries documented | PASS |
| ADRs reviewed | PASS |
| README and limitations match implementation | PASS |
| Fixture screenshots and video inspected | PASS |

The independent review followed the repository reviewer profile in a read-only
agent. It verified test isolation, checked the evidence tables against the
recorded data and caught a case-sensitive documentation link and an imprecise
artifact description. Both were corrected.
