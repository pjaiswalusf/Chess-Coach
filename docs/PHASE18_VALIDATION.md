# Phase 18 validation

## Historical candidate sample

On 9 November 2026, the generator verified 20 candidate mistakes with
Stockfish 19 on a migrated disposable copy of a 30-game local benchmark.
The benchmark used real historical PGNs with file-declaration provenance.
All 20 source PGNs matched the existing local archive byte for byte. The
sample had one verification thread, a 512 MB hash, and 125,000 / 500,000
node budgets. Both passes were checked against Stockfish's final best move.

| Run | Examined | Accepted | Rejected | Already stored | Unexpected errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| First | 20 | 4 | 16 | 0 | 0 |
| Same profile and candidates | 20 | 0 | 16 | 4 | 0 |

The rejection breakdown was 10 ambiguous, four below the teaching-value
criteria, and two unstable. A source replay audit verified the original
pre-move FEN, tracked player's turn, and historical move on all 20 candidates.
The accepted lines were replayed and checked against both saved ranked
searches. A sample review found one otherwise clear move still left the
solver more than ten pawns down. The final policy excludes such positions
through a −150 centipawn minimum for ordinary scores.

| Sample game / ply | Solver | Historical move | Verified move | Theme |
| --- | --- | --- | --- | --- |
| 1 / 39 | White | Re5 | Qxa6 | Critical capture |
| 2 / 14 | Black | Nxd4 | Bxd3 | Critical capture |
| 4 / 19 | White | gxf3 | Qxf3 | Critical capture |
| 4 / 29 | White | d3 | Qxe7+ | Forcing check |

These counts describe this sample under the recorded engine and policy.
Difficulty is heuristic. The sample supplies no post-training game evidence
for a real-game improvement claim.

## Repeatable verification

Backend commands from the repository root:

```sh
uv run ruff check .
uv run mypy src
uv run pytest
uv run pytest -o addopts= -m engine tests/integration/test_stockfish_real.py
```

Frontend commands from `frontend/`:

```sh
pnpm lint
pnpm check
pnpm test
pnpm build
pnpm test:e2e
PHASE18_TRAINING_DB=/absolute/path/to/migrated-training.db pnpm test:e2e e2e/training-live.spec.ts
```

The live browser test needs two new puzzles for one player, Python's project
environment, and a free local FastAPI port. It makes a disposable database
copy and captures the board before an attempt, both feedback states, and
the activity summary. It deliberately drops the first committed response,
retries it, restarts FastAPI, and checks the original grade, persisted
review time and streak, exactly one stored attempt for the submission, and
updated statistics. Stockfish and Ollama are disabled during the exercise.

Ruff and mypy passed. Pytest passed 664 standard tests with one skip,
plus all three opt-in Stockfish tests. Frontend lint, type checking, and build
passed. Vitest passed 37 tests and Playwright passed 39, including the real
training flow. Two unrelated opt-in browser tests were skipped.

The standard backend suite covered 5,015 of 5,596 executable lines
(89.6%). The Phase 18 deterministic domain subset covered 84 of 88 lines
(95.5%) across `domain/training.py` and `domain/review_schedule.py`.

The focused tests cover invalid and ambiguous engine evidence, mixed-depth
MultiPV, reported mate, White and Black score orientation, malformed and
illegal moves, promotion and castling selection, duplicate and conflicting
submissions, concurrent attempts, rollback after insertion, migration
round trips, engine unavailability, origin rejection, and comparable-game
thresholds. Synthetic game comparisons include a different exact time
control, another time class, a game on the cutoff, and damaged analysis.

An independent read-only review followed the repository's
`.cursor/agents/reviewer.md` checklist. Review findings addressed before
verification included MultiPV's final move, immediate mate validation, and
excluding incomplete game analysis from progress statistics.

## Local upgrade

The configured database migrated from `2f6cd65e0963` to `c18a001` with all 646
stored games retained and SQLite's quick check passing. Those legacy rows
lack archived completion evidence and completed analysis. The browser and
engine acceptance run used the disposable historical sample described above.
