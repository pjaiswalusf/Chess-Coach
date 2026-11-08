# Phase 12 validation — 2026-11-08

Baseline revision: `782d38881fd3f7c7b8c6d61c1b21b388ed9f69c6`, clean worktree,
393 tests passing, Ruff/mypy passing. Python 3.14 and the existing dependencies
were retained. No live migration, schema change, repair or source-data mutation
was performed; this implementation adds no schema changes. The existing database's SQLite backup contained 646 games; structural
integrity returned `ok` and foreign-key checks returned no violations. The backup
was created through SQLite's backup API, not a main-file-only WAL copy.
The live backup is at Phase 10 revision `2f6cd65e0963`, has no completed engine
analyses and no Phase 11 feature table. It is **not analytics-ready**. Analytics
preflight and performance validation therefore use the existing isolated Phase 11
30-game analyzed corpus; the user must apply the existing Phase 11 migration and
prepare compatible analysis/features before reporting on the live history. No
historical rows were removed or reanalyzed to conceal this readiness limitation.

## Delivered and verified

Read-only analytics contracts/cohorts/metrics/patterns/health/service, one batched
SQLite adapter, an offline `analytics-health` CLI, versioned preliminary support
and CP-severity policies, typed reports, deterministic category rankings, source
references, operating documentation and a reproducible offline benchmark script.
Existing Phase 11 modules are unchanged. No frontend, API endpoint, engine, LLM,
network, dependency or persistent-summary work was introduced.

| Check | Result |
| --- | --- |
| `uv run ruff check .` | Pass |
| `uv run mypy src` | Pass, 66 source files |
| `uv run pytest --cov=chess_coach --cov-report=json --cov-report=term-missing -q` | 499 passed; 2 opt-in engine tests deselected |
| `git diff --check` | Pass |
| New Phase 12 core + adapter coverage | 635/655 executable lines, 96.95% |
| All analytics modules + adapter | 815/835 executable lines, 97.60% |
| Entire backend coverage | 3051/3237 executable lines, 94.25% |

Core subset: `analytics/{cohorts,contracts,health,metrics,patterns,sample_policy,service}.py`
and `infrastructure/persistence/analytics_repository.py`. Coverage includes all
production files, including unimported drafts. The existing python-chess asyncio
deprecation warning remains. Line coverage is diagnostic, not proof of chess or
statistical correctness.

The 106 new tests include exact 295-total/73.75-mean/57.5-median CP arithmetic,
mutually exclusive 25/100 error rates, win-versus-score percentage, weighted
pooled means, missing/mate and zero denominators, all five windows, offset-aware
half-open UTC boundaries, deterministic ties, 18/20 partial membership, color and
clock-rule partitions, exact ECO counts, early-error incidence/median, low-sample
suppression, support/clock boundaries, context complements and overlap, Black
score orientation, legal capture/check response contexts, pre-move versus post-move
clocks, sustained conversion/recovery, repeated crossings, final opponent-move
collapse, castling eligibility, ranking ties/severity, report round trips, invalid
references and nested metric consistency. Test fixtures need no public network,
Ollama or real Stockfish.

Migrated SQLite tests exercise actual persisted move/position/feature evidence
prepared with the existing fake engine. They verify selected-player isolation,
read-only source comparisons, bounded query count, and a concurrent writer commit
between cohort and evidence reads. Corruption scenarios include missing moves,
negative/non-finite/wrong loss, wrong mover/version/profile/source/history/score,
missing provenance/positions, contradictory severity, invalid features/phases,
hash/index-column mismatch and a truncated feature snapshot. Source failures stop
ranking, not just add a cosmetic warning.

The planted fixture spreads 200 opportunities in each phase across 20 games:
opening 4/200 = 2%, middlegame 6/200 = 3%, endgame 24/200 = 12%. ENDGAME ranks first
with priority 24.0; a two-game opening is suppressed. Color imbalance is exactly
2/100 White versus 10/100 Black; time-class composition remains visible.

## Measured performance and remaining performance target

All measurements used isolated backups, with subprocess creation and sockets
patched to fail during preparation/reporting. Both reports repeat identically.
The live database and source corpora were not migrated or altered.

| Workload | DB reads | Evidence validation | Aggregation | Ranking | Warm total |
| --- | ---: | ---: | ---: | ---: | ---: |
| 30 unique historical games / 888 player moves | 0.0398 s | 0.4714 s | 0.0036 s | 0.0009 s | 0.5198 s |
| 1,000 replicated records / 29,527 player moves | 1.4075 s | 15.5556 s | 0.1347 s | 0.0343 s | 17.2484 s |

The 1,000-record workload is explicitly a **synthetic load test replicated from
30 independent source games**, not 1,000 independent histories and not evidence
for player-pattern quality. There are only 30 unique previously analyzed source
games available. No new Stockfish work was started to enlarge that corpus.
Source games/positions are legally validated and retain compatible profile/history
identities; cloned games receive isolated IDs and matching regenerated features.

The proposed few-second target at 1,000 games is **not achieved**. Reads are batched,
and validation dominates the measured runtime; growth is roughly linear rather
than N+1 queries. The correctness/readiness implementation is delivered, while
optimization and validation against 1,000 independent real games remain open.
No caching or weaker validation was added to disguise the measurement.
Timings omit feature-preparation work and are local observations, not hardware-wide
performance guarantees. Logger totals also include schema construction and adapter
overhead outside the individual stage timers.

Raw results: [historical](benchmarks/phase12-real.json),
[synthetic load](benchmarks/phase12-load1000.json). Reproduce with fresh destinations:

```sh
uv run python scripts/benchmark_phase12.py --source /path/to/analyzed-corpus.db \
  --database /private/tmp/phase12-real-new.db --output /private/tmp/phase12-real.json
uv run python scripts/benchmark_phase12.py --source /path/to/analyzed-corpus.db \
  --database /private/tmp/phase12-load-new.db --scale-games 1000 \
  --output /private/tmp/phase12-load.json
```

## Independent review

The existing `.cursor/agents/reviewer.md` profile was used for read-only independent
review. Initial findings fixed with regressions: an unrelated severity restriction
on castling eligibility, duplicate-game error reports failing validation, and SQL
UNKNOWN time-class filtering disagreeing with pure selection. Reviewer independently
reproduced checks, tests, mathematical expectations, snapshot/read-only behavior,
and the distinction between measured performance and the aspirational target.
Final independent review: **PASS for implementation**, with no unresolved critical
correctness findings. The reviewer independently reproduced Ruff, mypy, diff
checks, all 499 tests and the coverage totals above, and inspected benchmark
artifacts/methodology without rerunning the benchmark workloads. Live readiness
and the few-second / independent-1,000-game performance targets remain open;
Phase 12's operational gates are not marked fully complete.

## Acceptance evidence map

| Gate | Supporting verification |
| --- | --- |
| Cohorts selected before analysis | Pure last-N tests; migrated SQLite 18/20 test |
| Windows and UTC boundaries | `test_cohorts.py`; SQLite date/filter test |
| Missing/invalid/incompatible evidence | Unit health/contract tests; corrupt SQLite parameterized cases |
| Selected and analyzed counts distinct | Partial cohort tests and health schema |
| Database health and reconciliation | Backup health, migrated DB checks, nested/report validators |
| Score percentages | Exact 4-win/2-draw/4-loss fixture |
| Comparable-only mean and median | Five-move fixture with one missing loss |
| Explicit rate denominators | Move/context/outcome rate assertions and Rate validator |
| Phase/color/time-control reconciliation | Partition tests and final report validator |
| Zero denominators | Empty/mate-only/pending fixtures |
| Exact ECO and guards | 12/4/3 fixture; actual 9/10/11 opening boundary tests |
| Context opportunity populations | Check/capture/overlap/complement/strata tests |
| Clock semantics | SQLite 600+2 pre-clock versus 45-second post-clock test |
| Player-perspective conversion/recovery | Both-color synthetic outcomes and Black database orientation |
| Outcome versus collapse | Won-after-collapse and final-opponent-move regressions |
| Unsupported patterns suppressed | Partial/low-sample/unknown/clock guards |
| Deterministic versioned ranking | Explicit version fields; repeat/tie/severity tests |
| Supported references | Actual source-move membership validation and bad-reference regression |
| Planted endgame ranks first | Exact 2/3/12 fixture and priority assertion |
| Confounding preserved, no causal claim | Color/time composition and context strata fixtures |
| No engine or model during report | Static boundaries; patched fixture engine; blocked benchmark subprocess/socket calls |
| Read-only source | Before/after six-source-table comparison; query-only snapshot |
| Ruff/mypy/pytest | Full verification commands above |
| Core coverage | Exact coverage subset and totals above |
| Database integration | Migrated SQLite suite |
| Independent review | Final implementation PASS; live readiness/performance qualifications remain open |

Support cutoffs, CP severities, phase classification and sustained-advantage rules
are versioned product heuristics. Opening families remain unknown without a trusted
mapping. Recency weight is neutral; comparable-period trend analysis is deferred.
No conclusions about model quality, causation or statistically proven player
weaknesses are asserted. See [complete semantics](ANALYTICS.md).
