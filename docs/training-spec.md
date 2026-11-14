# Personalized training specification

## Source and puzzle contract

A puzzle starts immediately before the tracked player's mistake in a completed
standard chess game. It asks for either one engine-supported move or a sequence
of up to four solver moves. For a sequence, the app plays the opponent replies.
`source_ply` is 1-based relative to the PGN's main line. Ply 37 means replay the
first 36 half-moves. The PV supplies feedback after grading.

Generation selects a player and an existing analysis profile. Eligible moves
come from complete, current-version game analysis where the tracked player
moved. The preliminary filter is at least 120 centipawns lost, a missed winning
mate, or a move that newly allows an opponent mate from a centipawn position.
The stored loss uses the mover's perspective and excludes mate conversions.

The generator checks the original PGN, participant and result attribution,
historical move and FEN, and compatible cached evidence on both sides of the
move. It replays the main line with its actual move history and retains the
halfmove clock. Positions with fewer than two legal moves, terminal positions,
positions with a claimable threefold or 50-move draw, and games with unknown
pre-SetUp/FEN history are excluded. Automatic draw rules use the existing
`automatic-only-v1` policy. The stricter claimable-draw filter applies to puzzle
admission. Chess.com games require archived completion evidence. Stored file
games carry the completion declaration from the PGN.

## Verification and teaching policy, version 1

- Use the existing Stockfish adapter. Search MultiPV 3, or 2 when exactly two
  legal moves exist. Each search must supply a complete, unbounded iteration at
  one depth whose top move matches Stockfish's final best move. Validate all
  returned lines against the replayed board.
- Test at one quarter of the verification node budget and then at the full
  budget. The same move and teaching theme must pass both searches. The default
  is 125,000 and 500,000 nodes with one verification thread and the configured
  hash and wall-clock limit. Both searches start with fresh UCI game context.
  The higher budget is capped by `CHESS_COACH_STOCKFISH_MAX_NODES`.
- Interpret rankings from the solver's side and retain engine scores in White's
  perspective. For ordinary scores, require an 80-centipawn lead over the
  runner-up and a best score of at least −150 from the solver's side.
  For mate scores, accept a winning mate only when the next line lacks a
  winning mate. Reject mixed or mate-only rankings outside these rules.
  Verify a reported mate in one directly on the board. Keep mate distance
  separate from centipawns.
- Reject if the historical move is the verified best. Accept a winning mate,
  a forcing check, or a critical capture only after the verification criteria
  pass. A mate in one is labeled easy, a longer forced mate hard, and verified
  checks and captures medium. Difficulty describes the heuristic category.
- Version 2 also accepts a longer verified line ending in checkmate, or a
  capture on a later solver turn that improves the solver's material balance
  by at least two points after the opponent's engine reply. For each later
  solver turn with multiple legal moves, both searches must agree on the
  decisive move or a uniquely shortest mate. A verified continuation may be
  enabled on an unattempted puzzle using its original stored solution.
- The solution, original engine evidence and source link are immutable once published. Stored
  metadata includes both ranked searches, source and history fingerprints,
  engine version and settings, source profile, and generator version. A
  one-line historical engine cache is compatible for source validation.
  MultiPV verification has separate inputs. Existing published puzzles skip
  engine verification on repeated generation.

The policy is a conservative search heuristic. The acceptance sample is recorded
in [Phase 18 validation](PHASE18_VALIDATION.md).

## Local generation and recovery

Sync queues each newly imported Chess.com game for analysis after PGN
validation. The analysis worker scans completed analysis for puzzle candidates
from that run and saves accepted puzzles directly to Puzzles. The worker
saves its scan cursor between batches and retries verification errors. The
usual review schedule applies once a puzzle has been attempted.

For a manual backfill of older analyses:

Run `uv run alembic upgrade head` and finish or cancel any queued analysis. Stop
the analysis or combined coaching worker to release the shared engine lock.
Find the tracked player ID at `GET /api/v1/player` and the hash on a completed
run at `GET /api/v1/analysis-runs/{run_id}`. For a PGN-only database, use its
tracked player ID. The browser uses the configured Chess.com owner or the
single PGN owner when there is no configured Chess.com owner.

```sh
uv run chess-coach training generate --player-id 1 --profile PROFILE_HASH --limit 30
```

Generation is local and uses one engine process. The default candidate cap is
30. Change it with `CHESS_COACH_TRAINING_CANDIDATE_LIMIT`, verification threads
with `CHESS_COACH_TRAINING_STOCKFISH_THREADS`, and verification nodes with
`CHESS_COACH_TRAINING_VERIFICATION_NODES`. The source analysis settings continue
to apply to ordinary historical analysis.

Batches advance by stored move-analysis ID within the chosen profile. Pass
`--after-move-id` with the report's `next_after_move_id` to inspect the next
batch. On a failure, the report includes a safe retry cursor where applicable.
After reanalysis, start at zero to rediscover candidates. The source tuple
(player, game, ply) is unique, so restarting at zero is safe. Generation and
review leave the historical analysis records intact.

## Grading and review

`GET /api/v1/training/next` prioritizes due reviews ahead of new puzzles. New
puzzles alternate formats when both are available. The public puzzle contains FEN, side to move,
difficulty, theme, prior-attempt count and legal move choices. The grade,
historical move, solution, and PV are revealed after a legal attempt at
`POST /api/v1/training/{puzzle_id}/attempts` for one-move puzzles. For a sequence,
`POST /api/v1/training/{puzzle_id}/play` replays the submitted moves and returns
the next position after the opponent reply, or the final grade. The first
incorrect move ends the attempt. A completed sequence counts as one attempt.

Selecting a legal destination or choosing a promotion submits the move.
After a wrong move, Puzzles explains the consequence using saved engine evidence
when available and offers a retry from the same position. The retry sends the
latest incorrect attempt ID. The saved solve streak counts consecutive
successful attempts across puzzles and resets on any incorrect attempt.

The backend uses python-chess to validate the submitted UCI move. Correctness
is exact equality with the immutable approved UCI, including the promotion
piece. Invalid or illegal moves return 422. Unknown puzzles return 404.
Retired or unavailable due states return 409. Stockfish and Ollama can both
be offline during practice.

An accepted answer saves one attempt and updates the review schedule in the
same SQLite transaction. Identical puzzle and submission IDs replay the
original grade and schedule, even after the API restarts. Reusing the same ID
with a different move returns 409. The browser preserves the submitted move
and ID while retrying a failed response. The attempt records its scheduler
version. A new puzzle is due at creation, in UTC.

| Scheduler v1 outcome | New streak | Next review from attempt |
| --- | ---: | ---: |
| Incorrect | 0 | 1 day |
| First consecutive correct | 1 | 3 days |
| Second consecutive correct | 2 | 7 days |
| Third consecutive correct | 3 | 14 days |
| Fourth or later consecutive correct | 4+ | 30 days |

## Activity and game performance

- `GET /api/v1/training/stats` counts persisted attempts. Accuracy is correct
  attempts divided by attempts. Average attempts divide by distinct practiced
  puzzles. Both return null at a zero denominator. Theme rates use that theme's
  attempt count. Due counts include active puzzles whose review time has arrived.
- `GET /api/v1/training/progress` splits completed games by their recorded
  `played_at` around the first accepted attempt. For archived Chess.com games
  this is the archive's completion timestamp. Games on the exact boundary are
  excluded. Comparisons separate exact time class, time control, color, and
  compatible engine analysis profile. Games with missing time metadata or
  invalid/incomplete move evidence are excluded.
- The numerator is tracked-player moves with a loss of at least 150 centipawns.
  The denominator is tracked-player moves with a numeric centipawn loss across
  all phases. A game must contribute at least one such move to count. Rates
  require at least 10 games and 100 scored moves per period. Absolute change is
  after minus before in errors per 100 moves. Relative change divides that
  difference by the baseline rate and is unavailable for a zero baseline.
  Game IDs, move counts, and error counts accompany the results. This is an
  observational comparison. Puzzle accuracy measures performance in practice.

The System page reports training table read availability, queue counts, and
known generation blockers independently of Ollama. The generation command
reports actual engine verification failures and per-reason rejections. The API
keeps the existing loopback and browser-origin checks on training mutations.
