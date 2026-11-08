# Phase 10 measured baseline

Measured locally on 2026-11-08 with Python 3.14.6 and Stockfish 19. These are
observations on this machine, not optimal-settings or engine-quality claims.
The sample is the first 10 / first 30 legally parsed completed PGNs in the
preflight database backup. The samples overlap and are not a held-out quality
corpus. Benchmark copies are explicitly PGN-declared completion inputs; this
never changes the original Chess.com records or bypasses their source checks.

| Metric | 10 games | 30 games |
| --- | ---: | ---: |
| Mainline plies | 445 | 1768 |
| Minimum–maximum plies per game | 14–80 | 14–139 |
| Required position contexts (N+1 per game) | 455 | 1798 |
| Successful new nonterminal engine searches | 423 | 1662 |
| Terminal contexts resolved without search | 4 | 12 |
| Cache hits | 28 | 124 |
| Cache misses (including terminal contexts) | 427 | 1674 |
| Cache hit rate / required contexts | 6.15% | 6.90% |
| Engine elapsed seconds | 5.269 | 20.096 |
| New positions / engine second | 80.29 | 82.70 |
| Total worker wall seconds | 6.267 | 23.322 |
| Completed games / wall second | 1.60 | 1.29 |
| Failed games | 0 | 0 |
| Repeat run skipped games | 10 | 30 |
| Repeat run engine calls | 0 | 0 |
| Peak resident memory | Not measured | Not measured |

Both use Threads=4, Hash=512 MB, 10,000 nodes, a 3-second search ceiling,
MultiPV=1, `single-v1`, `automatic-only-v1`, python-chess 1.11.2. The configured
hash size is not a measurement of total process memory. Engine time is about
84–86% of worker wall time; this establishes where most of the time goes.
Reconstruction, cache lookup, and finalization durations are emitted as
structured per-game logs. Failed/retried searches are not included in the
successful-new-search counter; these runs had no failures.

## Single-pass decision

Retain one configurable budget. The measured throughput does not establish a
need for selective deeper searches, and this phase does not assign definitive
mistake labels. No labeled quality study establishes a benefit from introducing
candidate selection, deep scoring, or MultiPV. Sessions 10.6–10.7 are therefore
deliberately deferred under AGENTS.md and the user's explicit condition.
This is not a claim that 10,000 nodes is sufficient for definitive coaching.
A future quality study should compare consistent before/after profiles against
held-out positions, reporting changed conclusions and added computation before
adding those features. A larger single budget already creates separate evidence.

## Hard-stop demonstration

A separate real-Stockfish subprocess received SIGKILL after exactly three games:
119 committed move rows survived. Restart completed all ten games with 445 move
rows and no duplicate `(game, ply, profile)` keys. A subsequent equivalent run
performed zero engine searches. During the first worker process, 79 FastAPI
TestClient progress requests succeeded; the maximum measured response time was
0.006064 seconds. This is an in-process API measurement alongside an independent
real worker, not a network latency benchmark.

The opt-in real browser/API/worker test also passed: UI submission, SIGKILL,
page closure/reopening, restart, repeat skip, distinct 20,000-node profile, and
actual move-evidence retrieval. See [validation](../PHASE10_VALIDATION.md).

Raw aggregate results: [10 games](phase10-10-games.json),
[30 games](phase10-30-games.json), [recovery](phase10-recovery.json).

## Reproduction

Use fresh destination paths; the scripts refuse to overwrite a database:

```sh
uv run python scripts/benchmark_phase10.py --games 10 --database /tmp/phase10-ten.db
uv run python scripts/benchmark_phase10.py --games 30 --database /tmp/phase10-thirty.db
uv run python scripts/verify_phase10_recovery.py /tmp/phase10-ten.db /tmp/phase10-crash.db
```

Supply `--source PATH` to the benchmark if the preflight backup is elsewhere.
No public-network or Ollama access is involved. Search estimates can vary with
multi-threaded Stockfish scheduling; cache compatibility does not claim bitwise
reproducibility of independent searches.
