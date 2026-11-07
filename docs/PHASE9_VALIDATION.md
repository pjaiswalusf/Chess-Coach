# Phase 9 verification

Verified on 2026-11-07 with Python 3.14.6 and the local UCI identity
`Stockfish 19`. The project remains on Python 3.14 as required by AGENTS.md.

The existing Phase 9 implementation was present at commit `fe23edb`.
Verification reproduced a real-engine failure caused by stale score-bound flags
in python-chess's aggregated analysis dictionary. The adapter now consumes
individual updates through a small UciProtocol extension, keeping the latest
complete unbounded score/PV update with its own depth and node count. It retains
python-chess's parsing, process ownership, and bounded SimpleEngine call.
Bound-only searches and interrupted streams fail explicitly.

Deterministic tests cover score orientation, mate separation, CP-only loss for
both colors, invalid positions/history/budgets, legal PV replay, claimable versus
automatic draws, process reuse, serialization, timeout/crash recovery, and cleanup.
Real-engine tests cover both mate directions, broad material-score orientation,
PV legality, caller immutability, ten analyses in one process, and owned-process
exit after normal and exceptional completion.

Reproduce verification with:

```sh
uv run ruff check .
uv run mypy src
uv run pytest
uv run pytest -m engine
uv run chess-coach doctor
git diff --check
```

The doctor performs initialization, ping, fixed-position analysis, legality
validation, and cleanup. Defaults remain Threads=4 and Hash=512 MB. They are not
claimed to be optimal: sustained throughput and Activity Monitor observations
have not been measured. No historical-game orchestration, persistent analysis
cache, HTTP position-analysis endpoint, or coaching generation is added.

The installed python-chess emits Python 3.16 deprecation warnings and may log
Stockfish's startup `info string Using 4 threads` as unexpected output. These did
not prevent verified startup, analysis, or cleanup.

A second reproduced defect allowed a retained engine with unconfirmed process
exit to appear usable. The adapter now marks that lifecycle state unavailable,
blocks startup/analysis, and retains ownership until a subsequent `close()`
confirms exit. Regression tests cover both analysis-failure and normal-shutdown
entry into that state, followed by cleanup and explicit restart.

Final checks: Ruff passed; mypy passed for 44 source files; 284 normal tests
passed; both opt-in real-engine tests passed; doctor reported OVERALL: PASS.
Independent review found no remaining blocking findings and separately ran
43 adapter, score-utility, and protocol tests successfully.
